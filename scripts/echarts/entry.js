// ECharts 按需打包入口：只含地图 / 柱状 / 饼图和用到的组件，产物为 site/vendor/echarts.custom.min.js。
// 重新打包见 CLAUDE.md「常用命令」。
import * as echarts from "echarts/core";
import { MapChart, BarChart, PieChart } from "echarts/charts";
import { TooltipComponent, VisualMapPiecewiseComponent, GridComponent, LegendScrollComponent, TitleComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([MapChart, BarChart, PieChart, TooltipComponent, VisualMapPiecewiseComponent, GridComponent, LegendScrollComponent, TitleComponent, CanvasRenderer]);
window.echarts = echarts;
