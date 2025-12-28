<script setup>
import { ref } from 'vue';
import { Globe, Map, LogIn, AlertCircle } from 'lucide-vue-next';
import SynapseQShell from '../components/SynapseQShell.vue';

const messages = ref([
  {
    id: 1,
    sender: 'bot',
    timestamp: '11:20',
    content: '您好。当前为访客模式。'
  },
  {
    id: 2,
    sender: 'user',
    timestamp: '11:21',
    content: '帮我查一下我的高数期末成绩。'
  },
  {
    id: 3,
    sender: 'bot',
    timestamp: '11:21',
    content:
      '很抱歉，无法访问您的个人成绩数据。此信息属于 **Person_info (个人隐私)** 集合，仅对已通过统一身份认证的师生开放。'
  }
]);

const handleSendMessage = (text) => {
  const newMsg = {
    id: messages.value.length + 1,
    sender: 'user',
    timestamp: '11:22',
    content: text
  };
  messages.value = [...messages.value, newMsg];
  setTimeout(() => {
    messages.value = [
      ...messages.value,
      {
        id: messages.value.length + 1,
        sender: 'bot',
        timestamp: '11:22',
        content: '权限不足。请点击左下角登录。'
      }
    ];
  }, 800);
};
</script>

<template>
  <SynapseQShell
    theme-color="green"
    header-title="访客通道 (Public Access)"
    header-badge="Standard 库已连接"
    :current-user="{ name: 'Anonymous Guest', role: 'Visitor', avatar: 'V' }"
    :sidebar-items="[
      { icon: Globe, label: '公开查询', active: true },
      { icon: Map, label: '校园地图', active: false },
      { icon: LogIn, label: '师生登录', active: false }
    ]"
    :messages="messages"
    @send-message="handleSendMessage"
  >
    <template #right-panel>
      <div class="bg-green-50 rounded-xl p-4 border border-green-100">
        <div class="text-xs font-bold text-green-800 mb-2 uppercase tracking-wide flex items-center gap-1">
          <Globe size="12" /> Standard 库运行中
        </div>
        <p class="text-xs text-green-700 leading-relaxed">
          系统当前仅连接到公开数据集。您可以自由查询校历、办事指南及校园新闻。如需访问个人数据，请登录。
        </p>
      </div>

      <div class="mt-4 p-3 bg-red-50 border border-red-100 rounded-lg flex items-start gap-2">
        <AlertCircle size="14" class="text-red-500 mt-0.5 flex-shrink-0" />
        <div class="text-xs text-red-700">
          <span class="font-bold">提示：</span> 刚才的请求因涉及隐私被拦截。
        </div>
      </div>
    </template>
  </SynapseQShell>
</template>


