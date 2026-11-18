export const GBA_MAP_NAME = "gba-real-boundaries";
export const WORLD_MAP_NAME = "world-background-boundaries";

export const gbaMapSources = [
  {
    name: "DataV GeoAtlas",
    detail: "Administrative boundary GeoJSON by adcode, cached locally for frontend map rendering.",
    url: "https://geo.datav.aliyun.com/areas_v3/bound/{adcode}.json"
  },
  {
    name: "World GeoJSON",
    detail: "Global country boundary GeoJSON used only as a muted land/ocean background board.",
    url: "https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json"
  },
  {
    name: "Greater Bay Area 9+2 city scope",
    detail: "Hong Kong, Macao, and nine Guangdong municipalities.",
    url: "https://www.bayarea.gov.hk/sc/about/the-cities.html"
  }
];

export const gbaCityMeta = [
  { adcode: 440100, name: "Guangzhou", nameZh: "广州", center: [113.280637, 23.125178], color: "#9fcef6" },
  { adcode: 440300, name: "Shenzhen", nameZh: "深圳", center: [114.085947, 22.547], color: "#ffe1a6" },
  { adcode: 440400, name: "Zhuhai", nameZh: "珠海", center: [113.553986, 22.224979], color: "#bfe7df" },
  { adcode: 440600, name: "Foshan", nameZh: "佛山", center: [113.122717, 23.028762], color: "#b7e1df" },
  { adcode: 441300, name: "Huizhou", nameZh: "惠州", center: [114.412599, 23.079404], color: "#cfead9" },
  { adcode: 441900, name: "Dongguan", nameZh: "东莞", center: [113.746262, 23.046237], color: "#c9ddd8" },
  { adcode: 442000, name: "Zhongshan", nameZh: "中山", center: [113.382391, 22.521113], color: "#c5e4dc" },
  { adcode: 440700, name: "Jiangmen", nameZh: "江门", center: [113.094942, 22.590431], color: "#f8d4b4" },
  { adcode: 441200, name: "Zhaoqing", nameZh: "肇庆", center: [112.472529, 23.051546], color: "#d8e8bd" },
  { adcode: 810000, name: "Hong Kong SAR", nameZh: "香港", center: [114.173355, 22.320048], color: "#d5d0ec" },
  { adcode: 820000, name: "Macao SAR", nameZh: "澳门", center: [113.54909, 22.198951], color: "#f1e2b8" }
];

export const gbaCityNameByRegion = new Map(
  gbaCityMeta.flatMap((city) => [
    [city.name, city.name],
    [city.nameZh, city.name],
    [`${city.nameZh}市`, city.name],
    [city.adcode, city.name]
  ])
);
