<script setup>
import { ref } from 'vue';
import { Search, BookOpen, FileText } from 'lucide-vue-next';
import SynapseQShell from '../components/SynapseQShell.vue';

const messages = ref([
  {
    id: 1,
    sender: 'bot',
    timestamp: '14:30',
    content:
      '欢迎访问同济大学学术资源库。已为您连接 **Knowledge 集合** (包含 IEEE/CNKI 镜像及内部科研年报)。'
  },
  {
    id: 2,
    sender: 'user',
    timestamp: '14:32',
    content: '汽车学院在自动驾驶领域最近有什么发表？'
  },
  {
    id: 3,
    sender: 'bot',
    timestamp: '14:32',
    content:
      '同济大学汽车学院智能网联测评基地近期在 **IEEE T-ITS** 发表了多篇关于“车路协同感知”的高水平论文。其中，李教授团队提出的 *Graph-based Trajectory Prediction* 模型在复杂路口场景下达到了 SOTA 效果。',
    sources: [
      {
        icon: BookOpen,
        label: 'Knowledge',
        title: 'IEEE Trans. 2024: V2X Prediction',
        color: 'bg-purple-50 text-purple-700 border-purple-200'
      },
      {
        icon: FileText,
        label: 'Knowledge',
        title: '汽车学院2024科研成果汇总.pdf',
        color: 'bg-purple-50 text-purple-700 border-purple-200'
      }
    ]
  }
]);

const handleSendMessage = (text) => {
  const newMsg = {
    id: messages.value.length + 1,
    sender: 'user',
    timestamp: '14:33',
    content: text
  };
  messages.value = [...messages.value, newMsg];
  setTimeout(() => {
    messages.value = [
      ...messages.value,
      {
        id: messages.value.length + 1,
        sender: 'bot',
        timestamp: '14:33',
        content: '(演示: 学者模式调用深度生成路径)'
      }
    ];
  }, 800);
};
</script>

<template>
  <SynapseQShell
    theme-color="purple"
    header-title="学术科研模式 (Academic Mode)"
    header-badge="Knowledge 库已连接"
    :current-user="{ name: 'Prof. Zhang (Guest)', role: 'Visiting Scholar', avatar: 'Dr' }"
    :sidebar-items="[
      { icon: Search, label: '综合检索', active: false },
      { icon: BookOpen, label: '学术资源', active: true },
      { icon: FileText, label: '项目合作', active: false }
    ]"
    :messages="messages"
    @send-message="handleSendMessage"
  >
    <template #right-panel>
      <div class="bg-white border border-purple-100 rounded-xl p-4 shadow-sm">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center text-purple-600 font-bold">
            PDF
          </div>
          <div>
            <div class="text-xs font-bold text-gray-800 line-clamp-1">V2X Trajectory Prediction</div>
            <div class="text-[10px] text-gray-500">IEEE T-ITS • 2024 Oct</div>
          </div>
        </div>
        <div class="text-[10px] text-gray-600 leading-relaxed mb-3">
          "Abstract: This paper proposes a novel graph neural network approach for..."
        </div>
        <button
          class="w-full py-1.5 bg-purple-50 text-purple-700 text-xs font-medium rounded hover:bg-purple-100 transition-colors"
        >
          下载全文 (校内网权限)
        </button>
      </div>
    </template>
  </SynapseQShell>
</template>


