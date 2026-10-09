import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, AriaComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
echarts.use([BarChart,LineChart,PieChart,GridComponent,TooltipComponent,LegendComponent,AriaComponent,SVGRenderer]);
window.RadarLibraries.echarts=echarts;
