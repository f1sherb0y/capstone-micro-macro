import type { EnterpriseMapNodeDTO, FlowLinkDTO, ProjectMapNodeDTO, SimulationRuntimeStateDTO } from "../types/simulation";

const cityPositions: Record<string, { x: string; y: string }> = {
  Zhaoqing: { x: "18%", y: "34%" },
  Guangzhou: { x: "51%", y: "23%" },
  Foshan: { x: "38%", y: "42%" },
  Dongguan: { x: "62%", y: "44%" },
  Shenzhen: { x: "76%", y: "36%" },
  "Hong Kong": { x: "80%", y: "72%" },
  Macau: { x: "55%", y: "84%" },
  Zhuhai: { x: "50%", y: "74%" },
  Zhongshan: { x: "45%", y: "60%" },
  Jiangmen: { x: "28%", y: "69%" },
  Huizhou: { x: "88%", y: "44%" }
};

export function toProjectPins(projects: ProjectMapNodeDTO[]) {
  return projects.map((project, index) => {
    const position = cityPositions[project.city] || { x: `${30 + index * 7}%`, y: `${32 + index * 6}%` };
    return {
      id: project.project_id,
      city: project.city,
      name: project.name,
      x: position.x,
      y: position.y,
      status: project.status,
      progress: Math.round(project.progress)
    };
  });
}

export function toEnterprisePins(
  enterprises: EnterpriseMapNodeDTO[] = [],
  links: FlowLinkDTO[] = [],
  maxNodes = 500
) {
  const linkedIds = new Set(links.flatMap((link) => [link.source_id, link.target_id]));
  const priority = (enterprise: EnterpriseMapNodeDTO) => {
    if (linkedIds.has(enterprise.agent_id)) return 0;
    if (enterprise.status === "active") return 1;
    if (enterprise.status === "standby") return 2;
    return 3;
  };
  const selected = [...enterprises]
    .sort((a, b) => priority(a) - priority(b) || a.city.localeCompare(b.city) || a.agent_id.localeCompare(b.agent_id))
    .slice(0, maxNodes);
  const cityCounts = new Map<string, number>();

  return selected.map((enterprise) => {
    const base = cityPositions[enterprise.city] || fromLngLat(enterprise.longitude, enterprise.latitude);
    const count = cityCounts.get(enterprise.city) || 0;
    cityCounts.set(enterprise.city, count + 1);
    const offset = radialOffset(count);
    const x = clampPercent(percentNumber(base.x) + offset.x);
    const y = clampPercent(percentNumber(base.y) + offset.y);
    return {
      id: enterprise.agent_id,
      name: enterprise.name,
      city: enterprise.city,
      role: enterprise.role,
      status: linkedIds.has(enterprise.agent_id) ? "linked" : enterprise.status,
      x: `${x}%`,
      y: `${y}%`,
      shortName: enterprise.name.replace(/SyntheticConstructionAgent|模拟/g, "").slice(0, 12),
      className: roleClass(enterprise.role)
    };
  });
}

export function toRuntimeFlowLines(
  links: FlowLinkDTO[] = [],
  enterprisePins: Array<{ id: string; x: string; y: string }> = [],
  projectPins: Array<{ id: string; x: string; y: string }> = []
) {
  const positions = new Map<string, { x: number; y: number }>();
  [...enterprisePins, ...projectPins].forEach((pin) => {
    positions.set(pin.id, { x: percentNumber(pin.x), y: percentNumber(pin.y) });
  });

  return links.slice(0, 80).map((link, index) => {
    const source = positions.get(link.source_id) || fromLngLatNumber(link.source_longitude, link.source_latitude);
    const target = positions.get(link.target_id) || fromLngLatNumber(link.target_longitude, link.target_latitude);
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const samePoint = Math.abs(dx) < 0.6 && Math.abs(dy) < 0.6;
    const bend = samePoint ? 5 + (index % 6) * 2 : Math.max(3, Math.min(12, Math.hypot(dx, dy) * 0.22));
    const sign = index % 2 === 0 ? 1 : -1;
    const c1x = samePoint ? source.x - bend : source.x + dx * 0.35 - sign * bend * 0.28;
    const c1y = samePoint ? source.y - bend * sign : source.y + dy * 0.25 + sign * bend;
    const c2x = samePoint ? target.x + bend : source.x + dx * 0.65 + sign * bend * 0.28;
    const c2y = samePoint ? target.y + bend * sign : source.y + dy * 0.75 - sign * bend;
    return {
      id: link.link_id,
      type: link.link_type,
      strength: link.strength,
      crossCity: link.cross_city,
      path: `M ${source.x.toFixed(2)} ${source.y.toFixed(2)} C ${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${target.x.toFixed(2)} ${target.y.toFixed(2)}`
    };
  });
}

export function runtimeToLegacyResult(runtime?: SimulationRuntimeStateDTO | null) {
  if (!runtime) return null;
  return {
    simulation_id: runtime.simulation_id,
    status: runtime.status,
    current_tick: runtime.current_tick,
    project_results: runtime.map.projects.map((project) => ({
      project_id: project.project_id,
      name: project.name,
      current_stage: project.stage,
      performance: {
        actual_progress: project.progress / 100,
        overall_quality: project.quality_score / 100,
        delay_days: project.delay_days,
        cost_overrun_ratio: project.cost_overrun_ratio
      }
    })),
    agent_results: runtime.map.enterprises.map((enterprise) => ({
      agent_id: enterprise.agent_id,
      name: enterprise.name,
      role: enterprise.role,
      region: enterprise.city
    }))
  };
}

function radialOffset(index: number) {
  if (index === 0) return { x: 0, y: 0 };
  const angle = index * 137.508 * (Math.PI / 180);
  const ring = Math.floor(Math.sqrt(index));
  const radius = 2.2 + ring * 1.15;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius * 0.72
  };
}

function roleClass(role: string) {
  if (role === "developer" || role === "owner") return "developer";
  if (role === "contractor") return "contractor";
  if (role === "supplier") return "supplier";
  if (role === "government") return "government";
  return "consultant";
}

function percentNumber(value: string) {
  return Number(String(value).replace("%", "")) || 0;
}

function clampPercent(value: number) {
  return Math.max(8, Math.min(92, Number(value.toFixed(2))));
}

function fromLngLat(longitude: number, latitude: number) {
  const point = fromLngLatNumber(longitude, latitude);
  return { x: `${point.x}%`, y: `${point.y}%` };
}

function fromLngLatNumber(longitude: number, latitude: number) {
  const minLng = 112.6;
  const maxLng = 115.4;
  const minLat = 21.8;
  const maxLat = 23.5;
  const x = 12 + ((longitude - minLng) / (maxLng - minLng)) * 76;
  const y = 84 - ((latitude - minLat) / (maxLat - minLat)) * 68;
  return { x: clampPercent(x), y: clampPercent(y) };
}
