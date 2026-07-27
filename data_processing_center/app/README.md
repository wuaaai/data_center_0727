# 数据处理中心前端静态界面

该目录是 `data_processing_center` 模块下的前端静态管理界面，技术栈为：

- Vue 3
- Element Plus
- Vite

## 目标

- 为数据处理中心提供后台管理风格的静态展示界面
- 左侧菜单对应数据处理中心 10 个模块
- 不依赖后端接口，仅做前端页面展示
- 默认开发端口为 `8000`

## 目录说明

- `package.json`：前端依赖与运行脚本
- `vite.config.js`：Vite 开发配置，端口固定为 `8000`
- `src/App.vue`：页面总入口
- `src/components`：界面组件
- `src/data/modules.js`：静态菜单和页面展示数据
- `src/styles.css`：全局样式

## 启动方式

```bash
npm install
npm run dev
```

启动后访问：

```text
http://localhost:8000
```
