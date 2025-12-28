// API基础配置
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://124.221.26.181:8000';
const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api/v1';

// Token管理
const getAccessToken = () => localStorage.getItem('access_token');
const getRefreshToken = () => localStorage.getItem('refresh_token');
const setTokens = (accessToken, refreshToken) => {
  localStorage.setItem('access_token', accessToken);
  if (refreshToken) {
    localStorage.setItem('refresh_token', refreshToken);
  }
};
const clearTokens = () => {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user_info');
};

// 通用请求函数
async function request(url, options = {}) {
  const token = getAccessToken();
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${BASE_URL}${API_PREFIX}${url}`, {
      ...options,
      headers,
    });

    // 处理401错误 - Token过期
    if (response.status === 401) {
      const refreshToken = getRefreshToken();
      if (refreshToken) {
        try {
          const refreshResponse = await refreshTokenAPI(refreshToken);
          if (refreshResponse.access_token) {
            setTokens(refreshResponse.access_token, refreshResponse.refresh_token);
            // 重试原请求
            headers['Authorization'] = `Bearer ${refreshResponse.access_token}`;
            return fetch(`${BASE_URL}${API_PREFIX}${url}`, {
              ...options,
              headers,
            }).then(res => res.json());
          }
        } catch (error) {
          clearTokens();
          throw new Error('Token已过期，请重新登录');
        }
      } else {
        clearTokens();
        throw new Error('未授权，请重新登录');
      }
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(errorData.detail || `请求失败: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    if (error.message.includes('fetch')) {
      throw new Error('网络错误，请检查连接');
    }
    throw error;
  }
}

// 认证API
export const authAPI = {
  // 用户登录
  async login(username, password) {
    const response = await request('/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    setTokens(response.access_token, response.refresh_token);
    if (response.user_info) {
      localStorage.setItem('user_info', JSON.stringify(response.user_info));
    }
    return response;
  },

  // 访客登录
  async guestLogin() {
    const response = await request('/guest-login', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    setTokens(response.access_token, response.refresh_token);
    if (response.user_info) {
      localStorage.setItem('user_info', JSON.stringify(response.user_info));
    }
    return response;
  },

  // 刷新Token
  async refresh(refreshToken) {
    const response = await request('/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    setTokens(response.access_token, response.refresh_token);
    if (response.user_info) {
      localStorage.setItem('user_info', JSON.stringify(response.user_info));
    }
    return response;
  },

  // 退出登录
  async logout() {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        await request('/logout', {
          method: 'POST',
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
      } catch (error) {
        console.error('Logout error:', error);
      }
    }
    clearTokens();
  },
};

// 会话管理API
export const sessionAPI = {
  // 创建新会话
  async createSession(type) {
    return await request('/session/new', {
      method: 'POST',
      body: JSON.stringify({ type }),
    });
  },

  // 获取会话列表
  async getSessionList(type) {
    return await request(`/session/list?type=${type}`, {
      method: 'GET',
    });
  },

  // 获取会话历史
  async getSessionHistory(sessionId) {
    return await request(`/session/${sessionId}/history`, {
      method: 'GET',
    });
  },

  // 删除会话
  async deleteSession(sessionId) {
    return await request(`/session/${sessionId}`, {
      method: 'DELETE',
    });
  },
};

// 聊天API
export const chatAPI = {
  // 发送消息（SSE流式响应）
  async sendMessage(type, query, sessionId, onChunk, onError, onComplete) {
    const token = getAccessToken();
    const headers = {
      'Content-Type': 'application/json',
    };
    
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      const response = await fetch(`${BASE_URL}${API_PREFIX}/chat/${type}`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          query,
          session_id: sessionId,
          stream: true,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(errorData.detail || `请求失败: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        
        if (done) {
          if (onComplete) onComplete();
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim() === '') continue;
          
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            
            if (data === '[DONE]') {
              if (onComplete) onComplete();
              return;
            }

            try {
              const json = JSON.parse(data);
              if (json.chunk && onChunk) {
                onChunk(json.chunk);
              }
            } catch (e) {
              console.error('Parse SSE data error:', e, data);
            }
          }
        }
      }
    } catch (error) {
      if (onError) {
        onError(error);
      } else {
        throw error;
      }
    }
  },
};

// 辅助函数：刷新Token（内部使用）
async function refreshTokenAPI(refreshToken) {
  const response = await fetch(`${BASE_URL}${API_PREFIX}/refresh`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    throw new Error('Token刷新失败');
  }

  return await response.json();
}

// 获取用户信息
export const getUserInfo = () => {
  const userInfoStr = localStorage.getItem('user_info');
  return userInfoStr ? JSON.parse(userInfoStr) : null;
};

// 检查是否已登录
export const isAuthenticated = () => {
  return !!getAccessToken();
};

