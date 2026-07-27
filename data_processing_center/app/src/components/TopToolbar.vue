<script setup>
defineProps({
  title: {
    type: String,
    required: true
  },
  subtitle: {
    type: String,
    required: true
  }
})
</script>

<template>
  <header class="top-toolbar">
    <div class="toolbar-title-group">
      <div class="toolbar-kicker">财政智能助手 / 数据处理中心</div>
      <h3>{{ title }}</h3>
      <p>{{ subtitle }}</p>
    </div>
  </header>
</template>

<style scoped>
.top-toolbar {
  position: sticky;
  top: 0;
  z-index: 6;
  padding: 18px 22px;
  border-radius: 24px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 252, 0.82));
  backdrop-filter: blur(18px);
  border: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.06);
}

.toolbar-kicker {
  color: #5263ff;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.toolbar-title-group h1 {
  margin: 10px 0 8px;
  font-size: 32px;
  line-height: 1.12;
  color: #0f172a;
}

.toolbar-title-group p {
  margin: 0;
  max-width: 920px;
  color: #64748b;
  line-height: 1.7;
  font-size: 14px;
}

@media (max-width: 768px) {
  .top-toolbar {
    padding: 16px 18px;
    border-radius: 20px;
  }

  .toolbar-title-group h1 {
    font-size: 26px;
  }
}
</style>
