from copy import deepcopy


CITY_COORDS = {
    "Guangzhou": {"latitude": 23.1291, "longitude": 113.2644},
    "Shenzhen": {"latitude": 22.5431, "longitude": 114.0579},
    "Hong Kong": {"latitude": 22.3193, "longitude": 114.1694},
    "Macau": {"latitude": 22.1987, "longitude": 113.5439},
    "Foshan": {"latitude": 23.0215, "longitude": 113.1214},
    "Zhuhai": {"latitude": 22.2711, "longitude": 113.5767},
    "Dongguan": {"latitude": 23.0207, "longitude": 113.7518},
    "Huizhou": {"latitude": 23.1115, "longitude": 114.4152},
    "Zhongshan": {"latitude": 22.5176, "longitude": 113.3928},
    "Jiangmen": {"latitude": 22.5787, "longitude": 113.0819},
    "Zhaoqing": {"latitude": 23.0472, "longitude": 112.4650},
}

GBA_1000_CLUSTER_COVERAGE = [
    "Shenzhen",
    "Guangzhou",
    "Hong Kong",
    "Foshan",
    "Dongguan",
    "Zhuhai",
    "Macau",
    "Zhongshan",
    "Huizhou",
    "Jiangmen",
    "Zhaoqing",
]

GBA_1000_CITY_MIX = {
    "Shenzhen": 20.5,
    "Guangzhou": 17.7,
    "Hong Kong": 16.7,
    "Foshan": 9.1,
    "Dongguan": 8.5,
    "Huizhou": 5.5,
    "Zhuhai": 4.7,
    "Jiangmen": 4.6,
    "Zhongshan": 4.5,
    "Macau": 4.3,
    "Zhaoqing": 3.9,
}

GBA_1000_ROLE_COMPOSITION = {
    "contractors": 38,
    "consultants": 34,
    "suppliers": 10,
    "developers": 19,
    "others": 0,
}

GBA_1000_ROLE_MIX_BY_CITY = {
    "Shenzhen": {"developers": 23.1, "contractors": 30.6, "consultants": 36.3, "suppliers": 10.0},
    "Guangzhou": {"developers": 19.9, "contractors": 38.1, "consultants": 32.0, "suppliers": 10.0},
    "Hong Kong": {"developers": 18.1, "contractors": 35.2, "consultants": 38.5, "suppliers": 8.2},
    "Foshan": {"developers": 16.1, "contractors": 42.7, "consultants": 29.1, "suppliers": 12.1},
    "Dongguan": {"developers": 15.1, "contractors": 43.7, "consultants": 30.7, "suppliers": 10.4},
    "Huizhou": {"developers": 10.4, "contractors": 50.5, "consultants": 26.4, "suppliers": 12.6},
    "Zhuhai": {"developers": 18.7, "contractors": 43.7, "consultants": 27.1, "suppliers": 10.4},
    "Jiangmen": {"developers": 11.1, "contractors": 50.9, "consultants": 24.8, "suppliers": 13.3},
    "Zhongshan": {"developers": 10.7, "contractors": 49.0, "consultants": 28.2, "suppliers": 12.1},
    "Macau": {"developers": 11.5, "contractors": 57.4, "consultants": 23.0, "suppliers": 8.0},
    "Zhaoqing": {"developers": 11.0, "contractors": 49.8, "consultants": 26.8, "suppliers": 12.4},
}


AGENTS = [
    {
        "agent_id": "O001",
        "name": "Shenzhen Bay Owner",
        "role": "Owner",
        "region": "Shenzhen",
        "status": "active",
        "ai_generated": False,
        "rating": 4.5,
        "project_count": 71,
        "tags": ["Developer", "Mixed-use", "Public-private"],
        "short_description": "A developer with strong financing and payment reliability.",
    },
    {
        "agent_id": "A001",
        "name": "GBA Design Studio",
        "role": "Architect",
        "region": "Guangzhou",
        "status": "active",
        "ai_generated": True,
        "rating": 4.4,
        "project_count": 69,
        "tags": ["BIM", "Green Design", "Approval Support"],
        "short_description": "A design institute focused on complex urban and green building projects.",
    },
    {
        "agent_id": "Q001",
        "name": "Pearl QS Consulting",
        "role": "QS",
        "region": "Hong Kong",
        "status": "active",
        "ai_generated": False,
        "rating": 4.3,
        "project_count": 65,
        "tags": ["Cost Control", "Tendering", "Final Account"],
        "short_description": "A QS firm with strong cost planning and cross-border tender support.",
    },
    {
        "agent_id": "C001",
        "name": "Guangdong Contractor A",
        "role": "Contractor",
        "region": "Guangzhou",
        "status": "active",
        "ai_generated": False,
        "rating": 4.2,
        "project_count": 60,
        "tags": ["Infrastructure", "Civil Works", "EPC"],
        "short_description": "A contractor with broad delivery capacity across public works.",
    },
    {
        "agent_id": "C002",
        "name": "Hong Kong Contractor B",
        "role": "Contractor",
        "region": "Hong Kong",
        "status": "active",
        "ai_generated": False,
        "rating": 4.5,
        "project_count": 78,
        "tags": ["International", "Quality Management", "Complex Projects"],
        "short_description": "A cross-border contractor with strong safety and quality systems.",
    },
    {
        "agent_id": "C003",
        "name": "Shenzhen Contractor C",
        "role": "Contractor",
        "region": "Shenzhen",
        "status": "active",
        "ai_generated": False,
        "rating": 4.6,
        "project_count": 82,
        "tags": ["Infrastructure", "Building Construction", "Industrial", "Digital BIM"],
        "short_description": "A leading general contractor with strong delivery capability.",
    },
    {
        "agent_id": "S001",
        "name": "Foshan Supplier",
        "role": "Supplier",
        "region": "Foshan",
        "status": "active",
        "ai_generated": False,
        "rating": 4.1,
        "project_count": 62,
        "tags": ["Materials", "Prefabrication", "Reliable Supply"],
        "short_description": "A supplier with stable material quality and regional logistics coverage.",
    },
    {
        "agent_id": "G001",
        "name": "GBA Regulator",
        "role": "Government",
        "region": "Shenzhen",
        "status": "active",
        "ai_generated": False,
        "rating": 4.7,
        "project_count": 94,
        "tags": ["Approval", "Safety Inspection", "Policy Guidance"],
        "short_description": "A public authority responsible for approval and regulatory inspections.",
    },
]


def agent_profile(agent_id: str) -> dict:
    agent = next((item for item in AGENTS if item["agent_id"] == agent_id), AGENTS[5])
    role = agent["role"]
    base = {
        "Contractor": {
            "scale": "Large Scale",
            "ownership": "Private",
            "employees": 3200,
            "annual_revenue": 12.8,
            "description": "A leading general contractor with strong delivery capability across public infrastructure, commercial, and industrial projects.",
            "capabilities": {
                "financial_strength": 4.4,
                "technical_capability": 4.5,
                "project_experience": 4.7,
                "innovation_level": 4.7,
                "compliance_level": 4.4,
            },
        },
        "Architect": {
            "scale": "Mid-size",
            "ownership": "Partnership",
            "employees": 720,
            "annual_revenue": 2.4,
            "description": "A design institute with strong BIM coordination and statutory approval support.",
            "capabilities": {
                "financial_strength": 3.7,
                "technical_capability": 4.6,
                "project_experience": 4.2,
                "innovation_level": 4.5,
                "compliance_level": 4.3,
            },
        },
        "QS": {
            "scale": "Consulting Firm",
            "ownership": "Private",
            "employees": 560,
            "annual_revenue": 1.8,
            "description": "A QS consultancy supporting cost planning, tendering, payment evaluation, and final account settlement.",
            "capabilities": {
                "financial_strength": 3.8,
                "technical_capability": 4.1,
                "project_experience": 4.4,
                "innovation_level": 3.8,
                "compliance_level": 4.5,
            },
        },
    }
    role_profile = base.get(role, base["Contractor"])
    profile = deepcopy(agent)
    profile.update(
        {
            "scale": role_profile["scale"],
            "ownership": role_profile["ownership"],
            "established_year": 2006,
            "employees": role_profile["employees"],
            "annual_revenue": role_profile["annual_revenue"],
            "service_scope": "GBA & National",
            "description": role_profile["description"],
            "capabilities": role_profile["capabilities"],
            "capability_tags": agent["tags"],
            "radar": role_profile["capabilities"],
            "recent_activities": [
                {
                    "activity_id": "ACT001",
                    "date": "2025-05",
                    "title": "Won a bid for a smart infrastructure project in Shenzhen",
                    "type": "bid",
                    "description": "Selected through a cross-regional tender evaluation process.",
                },
                {
                    "activity_id": "ACT002",
                    "date": "2025-04",
                    "title": "Completed green building certification for waterfront complex",
                    "type": "certification",
                },
                {
                    "activity_id": "ACT003",
                    "date": "2025-03",
                    "title": "Joined GBA Construction Low-Carbon Alliance",
                    "type": "collaboration",
                },
            ],
            "notes": "Strong experience in complex urban projects and green construction. Actively investing in digital delivery and cross-regional coordination.",
            "updated_at": "2026-05-19T10:06:00",
        }
    )
    return profile


CLUSTERS = [
    {
        "cluster_id": "CL005",
        "name": "GBA 1000 Enterprise Test Cluster",
        "cluster_type": "regional",
        "region": "GBA",
        "status": "ready",
        "agent_count": 1000,
        "structure_tag": "Real-first Balanced Mix",
        "ai_generated": False,
        "description": "A 1000-enterprise Greater Bay Area construction test cluster. It uses the official 2024 GBA GDP distribution as a city market-size proxy, prioritizes available real_user and real_public enterprises, fills remaining quotas with synthetic firms, and adds one city-level regulator per GBA city for approval workflows.",
        "coverage": GBA_1000_CLUSTER_COVERAGE,
        "composition": GBA_1000_ROLE_COMPOSITION,
        "city_mix": GBA_1000_CITY_MIX,
        "role_mix_by_city": GBA_1000_ROLE_MIX_BY_CITY,
        "role_mix_basis": "Official 2024 GBA GDP for city market size, and Batch001 real_user/real_public observations for city-level role tilt. The simulation role classes are not published as an official city cross-tab, so sparse cities are smoothed with construction-domain role floors.",
        "source_mix": {
            "real_user": 149,
            "real_public": 265,
            "synthetic": 586,
            "support_regulator": 11,
        },
        "recommended_run": {
            "agent_source": "database",
            "agent_count": 1000,
            "max_tender_invites": 30,
            "use_prior_network_edges": True,
            "enable_project_generation": True,
        },
    },
    {
        "cluster_id": "CL001",
        "name": "Greater Bay Area Construction Cluster",
        "cluster_type": "regional",
        "region": "GBA",
        "status": "ready",
        "agent_count": 126,
        "structure_tag": "Regional Mix",
        "ai_generated": False,
    },
    {
        "cluster_id": "CL002",
        "name": "Shenzhen Construction Enterprise Cluster",
        "cluster_type": "city",
        "region": "Shenzhen",
        "status": "ready",
        "agent_count": 42,
        "structure_tag": "High Activity",
        "ai_generated": False,
    },
    {
        "cluster_id": "CL003",
        "name": "Hong Kong Construction Enterprise Cluster",
        "cluster_type": "city",
        "region": "Hong Kong",
        "status": "ready",
        "agent_count": 31,
        "structure_tag": "International",
        "ai_generated": False,
    },
    {
        "cluster_id": "CL004",
        "name": "Cross-Border Project Delivery Cluster",
        "cluster_type": "project_delivery",
        "region": "GBA",
        "status": "ready",
        "agent_count": 29,
        "structure_tag": "Cross-Regional",
        "ai_generated": True,
    },
]


POLICIES = [
    {
        "policy_id": "POL001",
        "name": "Greater Bay Area Cross-Regional Collaboration Policy",
        "policy_type": "regulation",
        "region": "GBA",
        "status": "active",
        "parameter_count": 18,
        "tags": ["Entry Facilitation", "Approval Efficiency", "Qualification Recognition"],
    },
    {
        "policy_id": "POL002",
        "name": "Low-Carbon Construction Incentive Scheme",
        "policy_type": "sustainability",
        "region": "Shenzhen",
        "status": "active",
        "parameter_count": 16,
        "tags": ["Incentives", "Low Carbon", "Prefabrication"],
    },
    {
        "policy_id": "POL003",
        "name": "Digital Construction Adoption Programme",
        "policy_type": "technology",
        "region": "Hong Kong",
        "status": "active",
        "parameter_count": 20,
        "tags": ["Digital BIM", "Data Standards", "Innovation"],
    },
    {
        "policy_id": "POL004",
        "name": "Public Project Procurement Reform",
        "policy_type": "procurement",
        "region": "Guangzhou",
        "status": "draft",
        "parameter_count": 14,
        "tags": ["Tendering", "Compliance", "Transparency"],
    },
]


WORKFLOW = {
    "workflow_id": "WF001",
    "name": "GBA Cross-Regional Policy Scenario",
    "selected_cluster_id": "CL005",
    "selected_agent_ids": ["O001", "A001", "Q001", "C001", "C002", "C003", "S001", "G001"],
    "horizon_years": 5,
    "time_step": "monthly",
    "trigger_mode": "scheduled_event_based",
    "output_mode": "full_trace",
    "phases": [
        {"phase_id": "PH001", "name": "Baseline Simulation", "start_tick": 0, "end_tick": 24, "phase_type": "baseline"},
        {"phase_id": "PH002", "name": "Continue Simulation", "start_tick": 24, "end_tick": 60, "phase_type": "continuation"},
    ],
    "interventions": [
        {
            "intervention_id": "INT001",
            "policy_id": "POL001",
            "name": "Cross-Regional Collaboration Policy",
            "apply_tick": 24,
            "target_scope": "all_agents",
            "target_roles": [],
            "target_regions": ["Hong Kong", "Shenzhen", "Guangzhou", "Macau", "Zhuhai"],
        }
    ],
    "events": [],
    "execution_logic": {
        "baseline_duration_years": 2,
        "policy_application_tick": 24,
        "continuation_duration_years": 3,
    },
}
