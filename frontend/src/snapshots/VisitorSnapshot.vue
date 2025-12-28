<script setup>
import { ref } from 'vue';
import { Globe, Map, LogIn, ChevronRight } from 'lucide-vue-next';
import SynapseQShell from '../components/SynapseQShell.vue';

const messages = ref([
  {
    id: 1,
    sender: 'bot',
    timestamp: '10:00',
    content:
      '您好！我是 SynapseQ 访客助手。我可以为您提供同济大学的 **公开信息**，如校区导航、院系简介和招生政策。'
  },
  {
    id: 2,
    sender: 'user',
    timestamp: '10:01',
    content: '嘉定校区图书馆在哪里？'
  },
  {
    id: 3,
    sender: 'bot',
    timestamp: '10:01',
    content:
      '嘉定校区图书馆位于校区中轴线上，紧邻同心河，是嘉定校区的地标性建筑。具体地址为曹安公路4800号同济大学嘉定校区内。',
    sources: [
      {
        icon: Globe,
        label: 'Standard',
        title: '嘉定校区手绘地图.pdf',
        color: 'bg-green-50 text-green-700 border-green-200'
      }
    ]
  }
]);

const handleSendMessage = (text) => {
  const newMsg = {
    id: messages.value.length + 1,
    sender: 'user',
    timestamp: '10:02',
    content: text
  };
  messages.value = [...messages.value, newMsg];
  setTimeout(() => {
    messages.value = [
      ...messages.value,
      {
        id: messages.value.length + 1,
        sender: 'bot',
        timestamp: '10:02',
        content: '(演示: 访客模式仅能检索 Standard 库)'
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
          <Globe size="12" /> 当前权限范围
        </div>
        <p class="text-xs text-green-700 leading-relaxed">
          您当前处于匿名模式，仅可访问 <b>Standard (公开)</b> 集合。无法查询个人课表、内部会议纪要或学术论文全文。
        </p>
      </div>

      <div>
        <h4 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">
          热门公开问题
        </h4>
        <div class="space-y-2">
          <div
            v-for="q in ['四平路校区地图', '校车时刻表(仅公开版)', '2025本科招生简章']"
            :key="q"
            class="p-3 bg-white border border-gray-100 rounded-lg text-xs text-gray-600 hover:border-green-200 hover:text-green-700 cursor-pointer transition-colors flex items-center justify-between group"
          >
            {{ q }}
            <ChevronRight size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </div>
      </div>
    </template>
  </SynapseQShell>
</template>


