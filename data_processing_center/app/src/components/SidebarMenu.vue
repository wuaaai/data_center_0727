<script setup>
import {
  CollectionTag,
  Connection,
  Cpu,
  Monitor,
  Opportunity,
  Refresh,
  Timer
} from '@element-plus/icons-vue'

defineProps({
  modules: {
    type: Array,
    required: true
  },
  activeKey: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['change'])

const iconMap = {
  Connection,
  Refresh,
  CollectionTag,
  Cpu,
  Timer,
  Opportunity,
  Monitor
}
</script>

<template>
  <aside class="sidebar-shell">
    <div class="sidebar-top">
      <div class="brand-block">
        <div class="brand-mark">AI</div>
        <div class="brand-copy">
          <div class="brand-title">数据处理中心</div>
          <div class="brand-subtitle">Fiscal Data Console</div>
        </div>
      </div>
    </div>

    <div class="menu-section">
      <div class="menu-list">
        <button
          v-for="(item, index) in modules"
          :key="item.key"
          class="menu-item"
          :class="{ active: item.key === activeKey }"
          @click="emit('change', item.key)"
        >
          <div class="menu-item-main">
            <el-icon class="menu-icon">
              <component :is="iconMap[item.icon]" />
            </el-icon>
            <div class="menu-copy">
              <div class="menu-name">{{ item.name }}</div>
              <div class="menu-desc">{{ item.shortName }}</div>
            </div>
          </div>
          <span class="menu-arrow">›</span>
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar-shell {
  width: 288px;
  height: 100vh;
  padding: 24px 18px 20px;
  background:
    radial-gradient(circle at top left, rgba(98, 114, 164, 0.18), transparent 28%),
    linear-gradient(180deg, rgba(16, 23, 37, 0.99), rgba(10, 15, 26, 1));
  color: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 22px;
  box-shadow: 24px 0 56px rgba(15, 23, 42, 0.24);
  overflow-y: auto;
}

.sidebar-shell::-webkit-scrollbar {
  width: 8px;
}

.sidebar-shell::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.22);
  border-radius: 999px;
}

.sidebar-top {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 4px 6px;
}

.brand-mark {
  width: 52px;
  height: 52px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  font-size: 20px;
  font-weight: 800;
  color: #ffffff;
  background: linear-gradient(135deg, #10132f, #080428);
  box-shadow: 0 14px 26px rgba(82, 99, 255, 0.34);
}

.brand-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.brand-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(226, 232, 240, 0.62);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.sidebar-intro-card {
  padding: 18px;
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.03));
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.sidebar-chip {
  display: inline-flex;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(82, 99, 255, 0.16);
  color: #d6deff;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 12px;
}

.sidebar-intro-title {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 8px;
}

.sidebar-intro-desc,
.menu-desc,
.footer-subtitle {
  color: rgba(226, 232, 240, 0.64);
}

.sidebar-intro-desc {
  font-size: 13px;
  line-height: 1.72;
}

.menu-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.menu-caption {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 6px;
}

.menu-caption span {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.menu-caption small {
  color: rgba(148, 163, 184, 0.72);
}

.menu-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.menu-item {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.08);
  border-radius: 22px;
  padding: 16px 16px 16px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: inherit;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.045);
  transition: transform 0.2s ease, background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.menu-item:hover {
  transform: translateX(4px);
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(148, 163, 184, 0.18);
  box-shadow: 0 16px 28px rgba(4, 10, 20, 0.22);
}

.menu-item.active {
  background: linear-gradient(180deg, rgba(55, 65, 81, 0.98), rgba(31, 41, 55, 0.98));
  border-color: rgba(148, 163, 184, 0.24);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 18px 30px rgba(3, 7, 18, 0.28);
}

.menu-item-main {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  text-align: left;
}

.menu-index {
  min-width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(248, 250, 252, 0.7);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.menu-item.active .menu-index {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.menu-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.08);
  display: grid;
  place-items: center;
  font-size: 18px;
  flex-shrink: 0;
}

.menu-item.active .menu-icon {
  background: rgba(255, 255, 255, 0.12);
}

.menu-copy {
  min-width: 0;
}

.menu-name {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.3;
}

.menu-desc {
  margin-top: 5px;
  font-size: 12px;
  line-height: 1.45;
}

.menu-item.active .menu-desc {
  color: rgba(255, 255, 255, 0.78);
}

.menu-arrow {
  font-size: 20px;
  color: rgba(255, 255, 255, 0.48);
}

.menu-item.active .menu-arrow {
  color: rgba(255, 255, 255, 0.92);
}

.sidebar-footer {
  margin-top: auto;
  padding: 16px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(148, 163, 184, 0.12);
  display: flex;
  align-items: center;
  gap: 14px;
}

.footer-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #5263ff, #7c6bff);
  color: #fff;
  font-weight: 700;
}

.footer-title {
  font-size: 15px;
  font-weight: 700;
}

.footer-subtitle {
  margin-top: 4px;
  font-size: 12px;
}

@media (max-width: 1080px) {
  .sidebar-shell {
    width: 100%;
    height: auto;
    max-height: 46vh;
  }
}
</style>
