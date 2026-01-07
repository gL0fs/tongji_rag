<script setup>
import { ref, watch, computed } from 'vue';
import { Menu, Database, X, Shield, MessageSquare, Plus, Trash2, LogOut } from 'lucide-vue-next';

const props = defineProps({
  themeColor: { type: String, default: 'blue' },
  currentUser: { type: Object, required: true },
  headerTitle: { type: String, required: true },
  headerBadge: { type: String, default: '' },
  conversationHistory: { type: Array, default: () => [] },
  currentConversationId: { type: String, default: '' },
  messages: { type: Array, default: () => [] },
  rightPanelContent: { type: Object, default: null },
  exampleQuestions: { type: Array, default: () => [] },
  welcomeTitle: { type: String, default: '欢迎使用 SynapseQ' },
  welcomeDescription: { type: String, default: '我是SynapseQ智能助手，有什么可以帮您的吗？' }
});

const emit = defineEmits(['send-message', 'new-conversation', 'switch-conversation', 'delete-conversation', 'logout']);

const inputText = ref('');
const sidebarOpen = ref(true);
const rightPanelOpen = ref(true);
const messagesEndRef = ref(null);

watch(
  () => props.messages,
  () => {
    requestAnimationFrame(() => {
      messagesEndRef.value?.scrollIntoView({ behavior: 'smooth' });
    });
  },
  { deep: true }
);

const themeStyles = computed(() => ({
  sidebarBg: 'bg-slate-900',
  avatarBg:
    props.themeColor === 'green'
      ? 'bg-green-600'
      : props.themeColor === 'purple'
        ? 'bg-purple-600'
        : 'bg-blue-600',
  botMsgBg:
    props.themeColor === 'green'
      ? 'bg-green-600'
      : props.themeColor === 'purple'
        ? 'bg-purple-600'
        : 'bg-blue-600',
  headerBadgeBorder:
    props.themeColor === 'green'
      ? 'border-green-100'
      : props.themeColor === 'purple'
        ? 'border-purple-100'
        : 'border-blue-100',
  headerBadgeBg:
    props.themeColor === 'green'
      ? 'bg-green-50'
      : props.themeColor === 'purple'
        ? 'bg-purple-50'
        : 'bg-blue-50',
  headerBadgeText:
    props.themeColor === 'green'
      ? 'text-green-700'
      : props.themeColor === 'purple'
        ? 'text-purple-700'
        : 'text-blue-700',
  headerBadgeDot:
    props.themeColor === 'green'
      ? 'bg-green-500'
      : props.themeColor === 'purple'
        ? 'bg-purple-500'
        : 'bg-blue-500'
}));

const handleSend = () => {
  if (!inputText.value.trim()) return;
  emit('send-message', inputText.value.trim());
  inputText.value = '';
};

const handleExampleClick = (question) => {
  emit('send-message', question);
};

const formatContent = (html) =>
  html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

const showWelcome = computed(() => {
  // 只有当完全没有消息时才显示欢迎页面
  return props.messages.length === 0;
});
</script>

<template>
  <div class="flex h-full bg-gray-50 font-sans text-slate-800 overflow-hidden relative">
    <div
      :class="`${sidebarOpen ? 'w-64' : 'w-0'} ${themeStyles.sidebarBg} text-white transition-all duration-300 flex flex-col overflow-hidden shadow-xl z-20`"
    >
      <div class="p-5 border-b border-slate-700 flex items-center justify-between">
        <div class="flex items-center gap-2 font-bold text-lg text-blue-400">
          <div class="w-8 h-8 rounded bg-blue-600 flex items-center justify-center text-white">S</div>
          SynapseQ
        </div>
      </div>

      <div class="flex-1 overflow-y-auto py-4">
        <div class="px-4 mb-3">
          <button
            @click="emit('new-conversation')"
            class="w-full px-3 py-2 rounded-md bg-slate-800 hover:bg-slate-700 text-white text-sm font-medium flex items-center gap-2 transition-colors border border-slate-700"
          >
            <Plus size="16" />
            新建对话
          </button>
        </div>
        <div class="px-4 mb-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">
          历史对话
        </div>
        <nav class="space-y-1 px-2">
          <div
            v-for="conversation in conversationHistory"
            :key="conversation.id"
            class="group relative"
          >
            <button
              @click="emit('switch-conversation', conversation.id)"
              class="w-full text-left px-3 py-2.5 rounded-md flex items-center gap-3 transition-colors relative"
              :class="
                currentConversationId === conversation.id
                  ? 'bg-slate-800 text-white shadow-sm border-l-2 border-blue-500'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-white'
              "
            >
              <MessageSquare class="w-4 h-4 flex-shrink-0" />
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium truncate">{{ conversation.title || '新对话' }}</div>
              </div>
            </button>
            <button
              @click.stop="emit('delete-conversation', conversation.id)"
              class="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded hover:bg-slate-700 text-slate-400 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <Trash2 size="14" />
            </button>
          </div>
          <div v-if="conversationHistory.length === 0" class="px-3 py-4 text-center text-slate-500 text-sm">
            暂无历史对话
          </div>
        </nav>
      </div>

      <div class="p-4 border-t border-slate-700 bg-slate-900">
        <div class="flex items-center gap-3 mb-3">
          <div
            :class="`w-10 h-10 rounded-full ${themeStyles.avatarBg} flex items-center justify-center text-sm font-bold shadow-lg`"
          >
            {{ currentUser.avatar }}
          </div>
          <div class="flex-1 overflow-hidden">
            <div class="font-medium truncate">{{ currentUser.name }}</div>
            <div class="text-xs text-slate-400 flex items-center gap-1">
              <Shield size="10" /> {{ currentUser.role }}
            </div>
          </div>
        </div>
        <button
          @click="emit('logout')"
          class="w-full px-3 py-2 rounded-md text-slate-300 hover:text-white hover:bg-slate-800 text-sm font-medium flex items-center justify-center gap-2 transition-colors border border-slate-700"
        >
          <LogOut size="16" />
          退出登录
        </button>
      </div>
    </div>

    <div class="flex-1 flex flex-col min-w-0 bg-white shadow-sm relative z-10">
      <header class="h-16 border-b flex items-center justify-between px-6 bg-white z-10">
        <div class="flex items-center gap-4">
          <button
            @click="sidebarOpen = !sidebarOpen"
            class="p-2 hover:bg-gray-100 rounded-full text-gray-500"
          >
            <Menu size="20" />
          </button>
          <h1 class="font-semibold text-gray-800">
            {{ headerTitle }}
          </h1>
        </div>
        <div class="flex items-center gap-3">
          <span
            class="hidden md:inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium border"
            :class="`${themeStyles.headerBadgeBg} ${themeStyles.headerBadgeText} ${themeStyles.headerBadgeBorder}`"
          >
            <div class="w-2 h-2 rounded-full animate-pulse" :class="themeStyles.headerBadgeDot" />
            {{ headerBadge }}
          </span>
          <button
            @click="rightPanelOpen = !rightPanelOpen"
            class="p-2 rounded-full text-gray-500 hover:bg-gray-100"
            :class="rightPanelOpen ? 'bg-slate-100 text-slate-600' : ''"
          >
            <Database size="20" />
          </button>
        </div>
      </header>

      <div class="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 bg-slate-50 scroll-smooth relative">
        <!-- Welcome Page -->
        <div v-if="showWelcome" class="flex items-center justify-center min-h-[calc(100%-4rem)]">
          <div class="max-w-3xl w-full text-center space-y-8 py-12">
            <div class="space-y-4">
              <div class="flex justify-center">
                <div
                  class="w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold shadow-lg"
                  :class="`${themeStyles.botMsgBg} text-white`"
                >
                  AI
                </div>
              </div>
              <div>
                <h2 class="text-3xl font-bold text-gray-800 mb-2">{{ welcomeTitle }}</h2>
                <p class="text-gray-500 text-lg">{{ welcomeDescription }}</p>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Messages List -->
        <template v-else>
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="flex"
            :class="msg.sender === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="flex max-w-3xl gap-4"
              :class="msg.sender === 'user' ? 'flex-row-reverse' : 'flex-row'"
            >
              <div
                class="w-10 h-10 rounded-full flex-shrink-0 flex items-center justify-center text-sm font-bold shadow-sm"
                :class="
                  msg.sender === 'user'
                    ? 'bg-slate-800 text-white'
                    : `${themeStyles.botMsgBg} text-white`
                "
              >
                {{ msg.sender === 'user' ? currentUser.avatar : 'AI' }}
              </div>

              <div class="space-y-2">
                <div
                  class="p-4 rounded-2xl shadow-sm text-sm leading-relaxed bg-white text-gray-800 border border-gray-100"
                  :class="msg.sender === 'user' ? 'rounded-tr-none' : 'rounded-tl-none'"
                >
                  <div v-html="formatContent(msg.content)" />
                </div>

                <div v-if="msg.sources?.length" class="flex flex-wrap gap-2 animate-fade-in-up">
                  <div
                    v-for="(src, idx) in msg.sources"
                    :key="idx"
                    class="flex items-center gap-2 px-3 py-1.5 rounded-md border text-xs font-medium cursor-pointer hover:opacity-80 transition-opacity shadow-sm"
                    :class="src.color"
                  >
                    <component :is="src.icon" class="w-3 h-3" />
                    <span class="opacity-75">{{ src.label }}:</span>
                    <span class="underline decoration-dotted">{{ src.title }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div ref="messagesEndRef" />
        </template>
      </div>

      <div class="p-4 bg-white border-t">
        <div class="max-w-4xl mx-auto relative">
          <textarea
            v-model="inputText"
            @keydown.enter.prevent="!$event.shiftKey && handleSend()"
            placeholder="向 SynapseQ 提问..."
            class="w-full pl-4 pr-14 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 resize-none text-sm shadow-inner"
            rows="1"
          />
          <button
            @click="handleSend"
            class="absolute right-2 top-2 p-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-md disabled:opacity-50"
            :disabled="!inputText.trim()"
          >
            <svg viewBox="0 0 24 24" class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <div
      :class="`${rightPanelOpen ? 'w-80' : 'w-0'} bg-white border-l border-gray-200 transition-all duration-300 overflow-hidden flex flex-col shadow-lg z-10`"
    >
      <div class="p-5 border-b bg-gray-50 flex justify-between items-center">
        <h3 class="font-semibold text-gray-700 flex items-center gap-2">
          <Database size="18" class="text-slate-500" /> 信息面板
        </h3>
        <button class="md:hidden" @click="rightPanelOpen = false">
          <X size="18" />
        </button>
      </div>
      <div class="p-5 flex-1 overflow-y-auto space-y-6">
        <slot name="right-panel">
          <div class="text-sm text-gray-500">右侧内容未提供</div>
        </slot>
      </div>
      <div class="p-4 border-t bg-gray-50 text-xs text-gray-500 flex justify-between items-center">
        <span>Latency: 28ms</span>
        <span class="flex items-center gap-1 text-green-600 font-medium">
          <div class="w-1.5 h-1.5 rounded-full bg-green-500" />
          Online
        </span>
      </div>
    </div>
  </div>
</template>


