<template>
  <div class="app-shell">
    <aside class="sidebar">
      <button class="brand-mark" aria-label="GBA Construction Simulation">
        <Building2 :size="34" />
      </button>
      <nav class="nav-stack">
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-item', { active: activeView === item.key }]"
          @click="navigateToView(item.key)"
        >
          <component :is="item.icon" :size="22" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="cityline" aria-hidden="true"></div>
    </aside>

    <main :class="['workspace', activeView === 'agent' ? 'agent-workspace' : '', activeView === 'workflow' ? 'workflow-workspace' : '', activeView === 'analytics' ? 'analytics-workspace' : '', activeView === 'analytics' && analyticsActiveTab === 'periods' ? 'periods-workspace' : '', activeView === 'policy' && ['detail', 'rules'].includes(policyMappingTab) ? 'policy-architecture-workspace' : '']">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p v-if="pageSubtitle" class="page-subtitle">{{ pageSubtitle }}</p>
        </div>
        <div class="top-actions">
          <label class="search-box">
            <Search :size="18" />
            <input placeholder="Search platform..." />
          </label>
          <span :class="['status-pill', backendOnline ? 'online' : 'offline']">
            {{ backendOnline ? "Backend Online" : "Backend Offline" }}
          </span>
          <button class="avatar-button">R</button>
          <ChevronDown :size="18" />
        </div>
      </header>

      <section v-if="activeView === 'agent'" class="view-grid agent-layout">
        <div class="left-column">
          <div class="tabs">
            <button :class="{ active: agentTab === 'agent' }" @click="agentTab = 'agent'">Agent</button>
            <button :class="{ active: agentTab === 'cluster' }" @click="agentTab = 'cluster'">Cluster</button>
          </div>

          <template v-if="agentTab === 'agent'">
            <section class="panel">
              <div class="panel-header">
                <div>
                  <h2>Enterprise Pool</h2>
                </div>
                <div class="button-row">
                  <span class="count-pill">{{ displayAgentTotal }}</span>
                  <button class="icon-button" @click="refreshAgentData" :disabled="agentLoading"><RefreshCw :size="18" /></button>
                </div>
              </div>
              <div class="pool-action-row">
                <button class="pool-action primary" @click="openAgentModal('create')" :disabled="agentLoading">
                  <Plus :size="16" />Create Agent
                </button>
                <button class="pool-action ai" @click="openAgentModal('ai')" :disabled="agentLoading">
                  <Sparkles :size="16" />AI Generate
                </button>
              </div>
              <div class="enterprise-controls">
                <div class="enterprise-search-row">
                  <label class="enterprise-search">
                    <Search :size="19" />
                    <input v-model="agentKeyword" placeholder="Search enterprises..." />
                  </label>
                  <button class="enterprise-filter-button" aria-label="Filter enterprises">
                    <Filter :size="20" />
                  </button>
                </div>
                <div class="enterprise-type-tabs" aria-label="Enterprise type filters">
                  <button
                    v-for="type in enterpriseTypeFilters"
                    :key="type"
                    :class="{ active: enterpriseTypeFilter === type }"
                    @click="setEnterpriseTypeFilter(type)"
                  >
                    {{ type }}
                  </button>
                </div>
                <label class="enterprise-region-select">
                  <Globe2 :size="20" />
                  <select v-model="enterpriseRegionFilter">
                    <option v-for="region in enterpriseRegionOptions" :key="region">{{ region }}</option>
                  </select>
                  <ChevronDown :size="18" />
                </label>
              </div>
              <div class="data-list">
                <button
                  v-for="agent in agentRows"
                  :key="agent.agent_id"
                  :class="['data-row', { selected: selectedAgentId === agent.agent_id }]"
                  @click="selectedAgentId = agent.agent_id"
                >
                  <span :class="['round-icon', roleColor(agent.role)]"><component :is="roleIcon(agent.role)" :size="19" /></span>
                  <span class="row-main">
                    <strong>{{ agent.name }}</strong>
                    <small>{{ roleDisplayName(agent.role) }} <MapPin :size="13" /> {{ agent.region }}</small>
                  </span>
                  <span class="dot online"></span>
                  <span class="muted">Active</span>
                  <span class="rating"><Star :size="14" /> {{ agent.rating }}</span>
                  <span :class="['agent-kind', agent.ai_generated ? 'virtual' : 'real']">
                    {{ agent.ai_generated ? "Virtual" : "Real" }}
                  </span>
                </button>
              </div>
              <div class="pagination">
                <span class="pagination-range">{{ agentPageStart }}-{{ agentPageEnd }} of {{ displayAgentTotal }}</span>
                <button :disabled="agentPage <= 1 || agentLoading" @click="goAgentPage(-1)" aria-label="Previous agent page"><ChevronLeft :size="16" /></button>
                <span>{{ agentPage }}</span>
                <button :disabled="agentPage >= agentTotalPages || agentLoading" @click="goAgentPage(1)" aria-label="Next agent page"><ChevronRight :size="16" /></button>
              </div>
            </section>

            <section class="panel profile-panel">
              <div class="profile-main">
                <span :class="['round-icon large', roleColor(selectedAgent.role)]"><component :is="roleIcon(selectedAgent.role)" :size="26" /></span>
                <div>
                  <h2>{{ selectedAgent.name }}</h2>
                  <p class="tagline">{{ selectedAgent.description || `${roleDisplayName(selectedAgent.role)} across ${selectedAgent.region} and GBA markets.` }}</p>
                  <div class="chip-row">
                    <span>{{ roleDisplayName(selectedAgent.role) }}</span><span>{{ selectedAgent.region }}</span><span>{{ selectedAgent.scale || "Large Scale" }}</span>
                  </div>
                </div>
              </div>
              <div class="agent-detail-tabs" role="tablist" aria-label="Agent detail sections">
                <button
                  v-for="tab in agentDetailTabs"
                  :key="tab.key"
                  :class="{ active: agentDetailTab === tab.key }"
                  @click="selectAgentDetailTab(tab.key)"
                >
                  {{ tab.label }}
                </button>
              </div>

              <template v-if="agentDetailTab === 'profile'">
              <div class="enterprise-stats">
                <div><Users :size="28" /><b>{{ selectedAgent.employees ? selectedAgent.employees.toLocaleString() : "3,200+" }}</b><span>Employees</span></div>
                <div><BarChart3 :size="28" /><b>¥{{ selectedAgent.annual_revenue || 12.8 }}B</b><span>Annual Revenue</span></div>
                <div><Clock3 :size="28" /><b>{{ selectedAgent.established_year || 2006 }}</b><span>Founded</span></div>
                <div><Target :size="28" /><b>Grade A</b><span>Qualification</span></div>
              </div>
              <div class="profile-grid">
                <div class="info-table">
                  <h3>Basic Info</h3>
                  <dl>
                    <dt>Established</dt><dd>{{ selectedAgent.established_year || 2006 }}</dd>
                    <dt>Employees</dt><dd>{{ selectedAgent.employees ? selectedAgent.employees.toLocaleString() : "3,200+" }}</dd>
                    <dt>Annual Revenue</dt><dd>¥{{ selectedAgent.annual_revenue || 12.8 }}B</dd>
                    <dt>Service Scope</dt><dd>{{ selectedAgent.service_scope || "GBA & National" }}</dd>
                  </dl>
                </div>
                <div>
                  <h3>Capability Summary</h3>
                  <div v-for="bar in selectedAgent.capabilities" :key="bar.label" class="metric-bar">
                    <span>{{ bar.label }}</span>
                    <div><i :style="{ width: `${bar.value * 20}%` }"></i></div>
                    <b>{{ bar.value.toFixed(1) }}/5</b>
                  </div>
                </div>
                <div>
                  <h3>Capability Radar</h3>
                  <div ref="agentRadarRef" class="small-chart"></div>
                </div>
              </div>
              <div class="bottom-notes">
                <div>
                  <h3>Recent Activities</h3>
                  <ul>
                    <li v-for="activity in selectedAgent.recent_activities || []" :key="activity.activity_id">{{ activity.title }}</li>
                    <li v-if="!selectedAgent.recent_activities">Won a bid for a smart infrastructure project in Shenzhen</li>
                  </ul>
                </div>
                <div>
                  <h3>Agent Notes</h3>
                  <p>{{ selectedAgent.notes || `${selectedAgent.name} is simulation-ready with project lifecycle participation, resource allocation, and policy response parameters.` }}</p>
                </div>
              </div>
              </template>

              <div v-else class="cognitive-panel">
                <div v-if="agentCognitiveLoading" class="empty-state small">Loading cognitive state...</div>
                <template v-else-if="selectedAgentCognitive">
                  <div v-if="agentDetailTab === 'memory'" class="cognitive-list">
                    <article v-for="memory in selectedAgentCognitive.memory.slice(0, 8)" :key="memory.memory_id" class="cognitive-card">
                      <div><strong>{{ humanizeKey(memory.memory_type) }}</strong><span>Month {{ memory.created_tick }}</span></div>
                      <p>{{ memory.content }}</p>
                      <small>{{ humanizeKey(memory.event_type) }} · importance {{ percent(memory.importance_score) }}</small>
                    </article>
                  </div>
                  <div v-else-if="agentDetailTab === 'belief'" class="cognitive-list">
                    <article v-for="belief in selectedAgentCognitive.beliefs" :key="belief.belief_id" class="cognitive-card belief-card">
                      <div><strong>{{ humanizeKey(belief.belief_type) }}</strong><span>{{ percent(belief.belief_value) }}</span></div>
                      <div class="belief-bar"><i :style="{ width: `${Math.round((belief.belief_value || 0) * 100)}%` }"></i></div>
                      <p>{{ belief.explanation }}</p>
                      <small>confidence {{ percent(belief.confidence) }} · evidence {{ belief.evidence_count }}</small>
                    </article>
                  </div>
                  <div v-else-if="agentDetailTab === 'strategy'" class="cognitive-grid">
                    <article class="cognitive-card emphasis">
                      <span>Primary strategy</span>
                      <strong>{{ humanizeKey(selectedAgentCognitive.strategy.primary_strategy) }}</strong>
                      <p>Strategy is deterministically derived from financial strength, bidding style, regional openness, quality orientation, and policy adaptability.</p>
                    </article>
                    <article
                      v-for="metric in strategyMetrics(selectedAgentCognitive.strategy)"
                      :key="metric.key"
                      class="cognitive-card compact"
                    >
                      <span>{{ metric.label }}</span>
                      <strong>{{ percent(metric.value) }}</strong>
                      <div class="belief-bar"><i :style="{ width: `${Math.round(metric.value * 100)}%` }"></i></div>
                    </article>
                  </div>
                  <div v-else class="cognitive-list">
                    <article v-for="trace in selectedAgentCognitive.decision_trace.slice(0, 12)" :key="trace.decision_id" class="cognitive-card">
                      <div>
                        <strong>{{ humanizeKey(trace.selected_action || trace.decision_type) }}</strong>
                        <span>{{ trace.tick == null ? "No tick" : `Month ${trace.tick}` }}</span>
                      </div>
                      <p>{{ trace.explanation || "Decision was recorded for audit and fallback analysis." }}</p>
                      <small>{{ trace.camel_used ? "CAMEL" : "Rule-based" }} · {{ trace.fallback_used ? "fallback used" : "validated" }}</small>
                    </article>
                    <div v-if="!selectedAgentCognitive.decision_trace.length" class="empty-state small">
                      No decision trace has been written for this agent yet.
                    </div>
                  </div>
                </template>
                <div v-else class="empty-state small">No cognitive state is available for this agent.</div>
              </div>
            </section>
          </template>

          <template v-else>
            <section class="panel">
              <div class="panel-header">
                <div>
                  <h2>Agent Cluster Library</h2>
                  <p>Built-in enterprise clusters for rapid use and customization</p>
                </div>
                <div class="button-row">
                  <button class="primary-button"><Plus :size="18" />Create Cluster</button>
                  <button class="ghost-button"><Sparkles :size="17" />AI Generate</button>
                </div>
              </div>
              <div class="filters">
                <select><option>All Cities</option></select>
                <select><option>All Types</option></select>
                <select><option>All Structures</option></select>
                <label class="inline-search"><Search :size="16" /><input placeholder="Search clusters..." /></label>
              </div>
              <div class="data-list">
                <button
                  v-for="cluster in clusterRows"
                  :key="cluster.name"
                  :class="['data-row', { selected: selectedCluster === cluster.name }]"
                  @click="selectedCluster = cluster.name"
                >
                  <span class="round-icon orange"><Building2 :size="19" /></span>
                  <span class="row-main"><strong>{{ cluster.name }}</strong><small>{{ cluster.type }} <MapPin :size="13" /> {{ cluster.region }}</small></span>
                  <span class="dot online"></span><span class="muted">{{ cluster.status }}</span>
                  <span class="muted"><Users :size="14" /> {{ cluster.size }}</span>
                  <span class="badge">{{ cluster.tag }}</span>
                </button>
              </div>
            </section>
            <section class="panel profile-panel">
              <div class="profile-main">
                <span class="round-icon large orange"><Building2 :size="26" /></span>
                <div>
                  <h2>{{ activeCluster.name }}</h2>
                  <p class="tagline">A simulation-ready enterprise cluster covering major construction firms, developers, consultants, and suppliers across the GBA.</p>
                  <div class="chip-row"><span>Regional Cluster</span><span>Greater Bay Area</span><span>Simulation Ready</span></div>
                </div>
              </div>
              <div class="profile-grid">
                <div class="info-table">
                  <h3>Basic Info</h3>
                  <dl>
                    <dt>City / Region</dt><dd>{{ activeCluster.region }}</dd>
                    <dt>Cluster Size</dt><dd>{{ activeCluster.size }}</dd>
                    <dt>Market Structure</dt><dd>{{ activeCluster.tag }}</dd>
                    <dt>Coverage</dt><dd>Hong Kong, Shenzhen, Guangzhou</dd>
                  </dl>
                </div>
                <div>
                  <h3>Composition Summary</h3>
                  <div v-for="item in clusterComposition" :key="item.label" class="metric-bar">
                    <span>{{ item.label }}</span><div><i :style="{ width: `${item.value}%` }"></i></div><b>{{ item.value }}%</b>
                  </div>
                </div>
                <div>
                  <h3>Cluster Fit</h3>
                  <div ref="clusterRadarRef" class="small-chart"></div>
                </div>
              </div>
            </section>
          </template>
        </div>

        <aside class="right-column">
          <section v-if="agentTab === 'agent'" class="panel chat-panel">
            <div class="workspace-header">
              <h2>Collaboration Workspace</h2>
              <span><i class="dot online"></i> Online</span>
            </div>
            <div class="assistant-hero">
              <div class="assistant-orb">
                <Users :size="36" />
              </div>
              <h2>Hello, Ryan</h2>
              <p>How can I help you today?</p>
            </div>
            <div class="workspace-actions">
              <button @click="sendQuickPrompt('Tell me about this company')"><FileText :size="20" />Tell me about this company<ChevronRight :size="18" /></button>
              <button @click="sendQuickPrompt('Explore project fit')"><BarChart3 :size="20" />Explore project fit<ChevronRight :size="18" /></button>
              <button @click="sendQuickPrompt('Request company documents')"><FolderOpen :size="20" />Request company documents<ChevronRight :size="18" /></button>
            </div>
            <div v-if="chatMessages.length" class="latest-reply">
              {{ chatLoading ? "Thinking with structured agent context..." : chatMessages[chatMessages.length - 1].text }}
            </div>
            <label class="chat-input workspace-input">
              <input v-model="chatInput" placeholder="Ask the agent about strategy, capability, or cooperation..." @keydown.enter.prevent="sendChatMessage" />
              <Send :size="18" @click="sendChatMessage" />
            </label>
            <p class="workspace-note">AI responses may contain inaccuracies.</p>
          </section>

          <section v-else class="panel cluster-preview">
            <div class="panel-header compact">
              <h2>Cluster Preview & Quick Use</h2>
              <span class="status-pill online">Available</span>
            </div>
            <div class="mini-map">
              <div v-for="city in cityNodes" :key="city.name" class="city-node" :style="{ left: city.x, top: city.y }">
                <span></span><b>{{ city.name }}</b>
              </div>
              <svg viewBox="0 0 100 60" preserveAspectRatio="none">
                <path d="M46 15 L64 28 L67 45 L44 45 L34 25 L46 15 L20 36 L34 25" />
                <path d="M67 45 L82 43 L64 28" />
              </svg>
            </div>
            <div class="split-cards">
              <div>
                <h3>Cluster Composition</h3>
                <div ref="clusterDonutRef" class="donut-chart"></div>
              </div>
              <div>
                <h3>Quick Use Options</h3>
                <button class="option-row"><FilePlus2 :size="18" />Use in Simulation<ChevronRight :size="16" /></button>
                <button class="option-row"><Copy :size="18" />Duplicate & Customize<ChevronRight :size="16" /></button>
                <button class="option-row"><Network :size="18" />Apply Market Structure<ChevronRight :size="16" /></button>
              </div>
            </div>
          </section>
        </aside>
      </section>

      <section
        v-else-if="activeView === 'policy'"
        :class="[
          'policy-mapping-page',
          {
            'policy-mapping-scroll-page': policyMappingTab !== 'library',
            'policy-scenario-page': policyMappingTab === 'scenarios',
            'atomic-rules-page': policyMappingTab === 'rules' && policyMappingWorkflowStep === 'rules'
          }
        ]"
      >
        <section class="panel mapping-workflow-strip">
          <div class="mapping-workflow-heading">
            <div>
              <h2>Policy Quantification Workflow</h2>
            </div>
            <div class="mapping-workflow-output" aria-label="Workflow output">
              <Package :size="14" />
              <span><small>Output</small><b>Simulation Scenario Portfolio</b></span>
            </div>
          </div>
          <div class="mapping-flow-rail">
            <button
              v-for="(step, index) in policyMappingWorkflow"
              :key="step.key"
              :class="['mapping-flow-step', { active: index === policyWorkflowActiveIndex, done: index < policyWorkflowActiveIndex }]"
              type="button"
              :disabled="step.key === 'review' && !policyExperimentConfirmedBlueprints.length"
              @click="openMappingWorkflowStep(step.key)"
            >
              <span>{{ index + 1 }}</span>
              <div>
                <b>{{ policyUi(step.label) }}</b>
                <small>{{ policyUi(step.description) }}</small>
              </div>
            </button>
          </div>
        </section>

        <template v-if="policyMappingTab === 'library'">
          <div :class="['policy-mapping-library-grid', { 'summary-closed': !policySummaryPanelOpen }]">
            <section class="panel mapping-library-panel">
              <div class="panel-header">
                <div>
                  <h2>Policy Mapping Library</h2>
                  <p>Browse existing policies, mapping progress, parameter versions, and review items.</p>
                </div>
                <div class="button-row mapping-library-actions">
                  <div class="mapping-total-pill header-count">
                    <FileText :size="17" />
                    <span><b>{{ policyMappingCatalog.length }}</b> policies</span>
                    <small v-if="policyMappingRows.length !== policyMappingCatalog.length">{{ policyMappingRows.length }} shown</small>
                  </div>
                  <div class="mapping-total-pill review header-count">
                    <AlertTriangle :size="17" />
                    <span><b>{{ policyMappingReviewPolicyTotal }}</b> in review</span>
                  </div>
                  <button class="ghost-button" type="button" @click="refreshPolicyData" :disabled="policyLoading">
                    <RefreshCw :size="16" />Refresh
                  </button>
                  <button class="primary-button" type="button" @click="openMappingTab('wizard')">
                    <FilePlus2 :size="16" />Add
                  </button>
                </div>
              </div>
              <div class="mapping-filter-row">
                <label class="enterprise-search">
                  <Search :size="18" />
                  <input v-model="policyKeyword" placeholder="Search policy name / domain / status..." />
                </label>
                <label class="enterprise-region-select">
                  <Globe2 :size="18" />
                  <select v-model="policyRegionFilter" aria-label="Policy mapping region filter">
                    <option v-for="region in policyRegionOptions" :key="region" :value="region">{{ policyUi(region) }}</option>
                  </select>
                  <ChevronDown :size="16" />
                </label>
                <label class="enterprise-region-select">
                  <SlidersHorizontal :size="18" />
                  <select v-model="policyTypeFilter" aria-label="Policy mapping type filter">
                    <option v-for="type in policyQuickTypeFilters" :key="type" :value="type">
                      {{ type === "All" ? "All Policies" : policyUi(type) }}
                    </option>
                  </select>
                  <ChevronDown :size="16" />
                </label>
              </div>

              <div class="mapping-policy-list">
                <article
                  v-for="policy in policyMappingRows"
                  :key="policy.id"
                  :class="['mapping-policy-row', { selected: selectedMappingPolicyId === policy.id }]"
                  @click="selectMappingPolicy(policy.id)"
                >
                  <button type="button" class="mapping-policy-main" @click="selectMappingPolicy(policy.id)">
                    <span :class="['round-icon', policy.color]"><component :is="policy.icon" :size="20" /></span>
                    <span>
                      <b>{{ policyUi(policy.name) }}</b>
                      <small>{{ policyUi(policy.type) }} · {{ policyUi(policy.project) }} · {{ policyUi(policy.region) }}</small>
                    </span>
                  </button>
                  <div class="mapping-policy-stats">
                    <span><b>{{ policy.clauses.length }}</b><small>Clauses</small></span>
                    <span><b>{{ policy.mechanisms.length }}</b><small>Mechanisms</small></span>
                    <span><b>{{ policy.macroVariables.length }}</b><small>Macro Vars</small></span>
                    <span><b>{{ policy.scenarios.length }}</b><small>Scenarios</small></span>
                    <span><b>{{ policy.atomicRules.length }}</b><small>Rules</small></span>
                    <span><b>{{ policy.reviewItems.length }}</b><small>Review</small></span>
                  </div>
                  <div class="mapping-policy-actions">
                    <span :class="['mapping-status', policy.stageTone]">{{ policyUi(policy.stageLabel) }}</span>
                    <button type="button" @click="selectMappingPolicy(policy.id); openMappingTab('detail')">
                      <FileCog :size="14" />View Mapping
                    </button>
                    <button type="button" @click="selectMappingPolicy(policy.id); openMappingTab('wizard')">
                      <SlidersHorizontal :size="14" />Adjust
                    </button>
                    <button type="button" @click="selectMappingPolicy(policy.id); openMappingTab('scenarios')">
                      <Sparkles :size="14" />Compose Scenarios
                    </button>
                  </div>
                </article>
              </div>
            </section>

            <aside v-if="policySummaryPanelOpen" class="panel mapping-summary-panel">
              <div class="panel-header compact">
                <h2>Current Mapping Summary</h2>
                <div class="button-row">
                  <span class="status-pill online">v{{ activeMappingPolicy.version }}</span>
                  <button class="icon-button mapping-summary-close" type="button" aria-label="Close policy mapping summary" @click="policySummaryPanelOpen = false">
                    <X :size="17" />
                  </button>
                </div>
              </div>
              <div class="mapping-summary-body">
                <div class="mapping-summary-hero">
                  <span :class="['round-icon large', activeMappingPolicy.color]"><component :is="activeMappingPolicy.icon" :size="28" /></span>
                  <div>
                    <h3>{{ policyUi(activeMappingPolicy.name) }}</h3>
                    <small>{{ policyUi(activeMappingPolicy.type) }} · {{ policyUi(activeMappingPolicy.region) }}</small>
                  </div>
                </div>
                <div class="mapping-summary-source">
                  <div>
                    <FileText :size="15" />
                    <small>Original Policy Text</small>
                  </div>
                  <p lang="zh-CN">{{ activeMappingPolicy.rawText }}</p>
                </div>
                <div class="mapping-chain">
                  <article v-for="item in activeMappingSummaryChain" :key="item.label">
                    <span><component :is="item.icon" :size="17" /></span>
                    <div>
                      <b>{{ policyUi(item.label) }}</b>
                      <small>{{ policyUi(item.value) }}</small>
                    </div>
                  </article>
                </div>
                <div class="mapping-summary-chips">
                  <span>{{ activeMappingPolicy.macroVariables.length }} Macro Variables</span>
                  <span>{{ activeMappingPolicy.atomicRules.length }} Rules</span>
                  <span>{{ activeMappingPolicy.reviewItems.length }} Review Items</span>
                </div>
                <div class="mapping-warning-card">
                  <AlertTriangle :size="18" />
                  <span>{{ policyUi(activeMappingPolicy.reviewItems[0]?.title || "No high-priority review item") }}</span>
                </div>
              </div>
            </aside>
          </div>
        </template>

        <template v-else-if="policyMappingTab === 'detail'">
          <div class="policy-detail-grid mechanism-mode">
            <section class="panel mapping-source-panel">
              <div class="panel-header compact">
                <div>
                  <small>Evidence input</small>
                  <h2>Source Policy Evidence</h2>
                  <p>Policy text, specificity, and clauses used as mapping evidence.</p>
                </div>
                <span class="count-pill" :aria-label="`${activeMappingPolicy.clauses.length} clauses`">
                  {{ activeMappingPolicy.clauses.length }}
                </span>
              </div>
              <div class="mapping-source-scroll">
                <article class="policy-text-card">
                  <div class="source-card-kicker">
                    <FileText :size="14" />
                    <small>Original Policy Text</small>
                  </div>
                  <p>{{ activeMappingPolicy.rawText }}</p>
                </article>
                <section class="structured-evidence-group">
                  <div class="source-clause-heading">
                    <div>
                      <small>Derived from policy text</small>
                      <b>Structured Evidence</b>
                    </div>
                  </div>

                  <div class="specificity-breakdown-card">
                    <div class="specificity-score-header">
                      <div>
                        <small>Evidence quality</small>
                        <b>Policy Specificity</b>
                      </div>
                      <span>{{ activePolicySpecificityScore }}</span>
                    </div>
                    <p>{{ policyUi(activePolicySpecificityLevel) }}</p>
                    <div class="specificity-dimension-list">
                      <article v-for="dimension in policySpecificityDimensions" :key="dimension.label">
                        <small :title="policyUi(dimension.label)">
                          <span
                            v-for="(word, wordIndex) in policyUi(dimension.label).split(' ')"
                            :key="`${dimension.label}-${wordIndex}`"
                          >
                            {{ word }}
                          </span>
                        </small>
                        <strong>{{ dimension.value }}</strong>
                      </article>
                    </div>
                  </div>

                  <div class="source-clause-subheading">
                    <b>Policy Clauses</b>
                    <span>{{ activeMappingPolicy.clauses.length }} extracted</span>
                  </div>

                  <div class="clause-list">
                    <article v-for="clause in activeMappingPolicy.clauses" :key="clause.id" class="clause-card">
                      <div>
                        <b>{{ clause.id }} · {{ policyUi(clause.type) }}</b>
                        <span>{{ policyUi(clause.path) }}</span>
                      </div>
                      <p>{{ clause.text }}</p>
                      <small>Specificity {{ clause.specificity }} · Target Roles {{ policyUi(clause.targets) }}</small>
                    </article>
                  </div>
                </section>
              </div>
            </section>

            <section class="panel mapping-detail-panel">
              <div class="panel-header">
                <div>
                  <small>Intervention design</small>
                  <h2>Intervention Architecture &amp; Quantification</h2>
                  <p>Define how each policy instrument acts, where it enters the process, which variable it changes, and at what implementation intensity.</p>
                </div>
                <button
                  class="primary-button"
                  type="button"
                  :disabled="selectedPolicyAtomicInstruments.length === 0"
                  @click="openMappingWorkflowStep('scenario')"
                >
                  <Layers3 :size="16" />Compose Scenarios
                </button>
              </div>

              <div class="mapping-detail-scroll">
                <section class="policy-step2-hero">
                  <div class="policy-goal-main">
                    <span class="section-eyebrow">Primary Policy Goal</span>
                    <h3>{{ activePolicyGoalProfile.primaryGoal }}</h3>
                    <p>{{ activePolicyGoalProfile.description }}</p>
                    <div class="goal-category-row prominent">
                      <em v-for="category in activePolicyGoalProfile.categories" :key="category">{{ category }}</em>
                    </div>
                  </div>
                  <div class="policy-package-profile">
                    <div class="package-profile-heading">
                      <div>
                        <span class="section-eyebrow blue">Package profile</span>
                        <b>Mixed Policy Package</b>
                      </div>
                      <span>{{ activePolicyLogicCoverage }}%</span>
                    </div>
                    <p>Multiple policy tools operate together across the participation journey.</p>
                    <div class="package-profile-metrics">
                      <span><strong>{{ activePolicyInterventionNodes.length }}</strong><small>Atomic tools</small></span>
                      <span><strong>{{ activePolicyTypeCount }}</strong><small>Types</small></span>
                      <span><strong>{{ activePolicyStageCount }}</strong><small>Stages</small></span>
                      <span><strong>{{ activePolicyModuleCount }}/5</strong><small>Modules</small></span>
                      <span><strong>{{ activePolicyRelations.length }}</strong><small>Relations</small></span>
                    </div>
                    <div class="package-profile-progress" aria-label="Policy instrument confirmation coverage">
                      <i :style="{ width: `${activePolicyLogicCoverage}%` }"></i>
                    </div>
                    <small>{{ selectedPolicyAtomicInstruments.length }} confirmed · {{ activePolicyInterventionNodes.length - selectedPolicyAtomicInstruments.length }} optional</small>
                  </div>
                </section>

                <section class="policy-bundle-panel">
                  <div class="section-title-row selectable">
                    <div>
                      <div class="bundle-map-title-line">
                        <h3>Intervention Bundle Map</h3>
                        <button
                          type="button"
                          class="bundle-map-help-trigger"
                          aria-label="How to read the Intervention Bundle Map"
                          aria-describedby="bundle-map-help-tooltip"
                        >
                          <Info :size="14" />
                          <span id="bundle-map-help-tooltip" class="bundle-map-help-tooltip" role="tooltip">
                            <b>How to read this map</b>
                            <span>
                              <strong>01</strong>
                              <span><b>Expected change</b><small>Natural-language policy hypothesis</small></span>
                            </span>
                            <span>
                              <strong>02</strong>
                              <span><b>Atomic decomposition</b><small>Tools, process stages, and relations</small></span>
                            </span>
                            <span>
                              <strong>03</strong>
                              <span><b>Model trace</b><small>Variables, Agent response, and outcome</small></span>
                            </span>
                            <em>Click an expected change to inspect its instruments and model mapping.</em>
                          </span>
                        </button>
                      </div>
                    </div>
                    <span>5 modules · 8 stages</span>
                  </div>

                  <div class="policy-bundle-map policy-module-overview-map">
                    <div class="module-overview-map-canvas">
                      <div class="module-overview-header">
                        <div>
                          <small>Intervention bundle</small>
                          <b>Expected change</b>
                        </div>
                        <div>
                          <small>Policy hypothesis</small>
                          <b>What should change?</b>
                        </div>
                        <div class="module-stage-header">
                          <em>Process coverage</em>
                          <div class="module-stage-axis">
                            <span
                              v-for="(stage, index) in policyProcessStages"
                              :key="`overview-heading-${stage.id}`"
                              :title="`${stage.label}: ${stage.description}`"
                            >
                              <b>{{ String(index + 1).padStart(2, "0") }}</b>
                              <small>{{ stage.shortLabel }}</small>
                            </span>
                          </div>
                        </div>
                        <span aria-hidden="true"></span>
                      </div>

                      <template v-for="module in activePolicyInterventionModules" :key="module.id">
                        <button
                          type="button"
                          :class="[
                            'module-overview-row',
                            module.tone,
                            {
                              selected: expandedPolicyModuleId === module.id,
                              gap: module.gap
                            }
                          ]"
                          :aria-expanded="expandedPolicyModuleId === module.id"
                          @click="expandPolicyModule(module.id)"
                        >
                        <div class="bundle-module-label">
                          <span>{{ module.index }}</span>
                          <div>
                            <b>{{ module.label }}</b>
                            <small>{{ module.description }}</small>
                          </div>
                        </div>

                        <div class="module-overview-statement">
                          <span class="module-change-icon"><component :is="module.icon" :size="17" /></span>
                          <div>
                            <small>Expected change · Model hypothesis</small>
                            <b>{{ module.expectedChange }}</b>
                            <div class="module-overview-meta">
                              <em v-if="module.gap">Coverage gap · no atomic instrument mapped</em>
                              <em v-else>{{ module.selectedCount }}/{{ module.instrumentCount }} instruments confirmed</em>
                              <span>{{ module.evidenceCount }} source {{ module.evidenceCount === 1 ? "clause" : "clauses" }}</span>
                            </div>
                          </div>
                        </div>

                        <div class="module-stage-coverage">
                          <span
                            v-for="(stage, stageIndex) in policyProcessStages"
                            :key="`${module.id}-${stage.id}`"
                            :class="{
                              active: isPolicyModuleStageActive(module, stageIndex),
                              start: stageIndex === module.startIndex,
                              end: stageIndex === module.endIndex
                            }"
                            :title="stage.label"
                          >
                            <i></i>
                          </span>
                          <div>
                            <b>{{ module.stageRange }}</b>
                            <small v-if="module.gap">Required coverage</small>
                            <small v-else>{{ module.instrumentCount }} atomic tools</small>
                          </div>
                        </div>

                          <ChevronRight :size="18" />
                        </button>

                  <section
                    v-if="expandedPolicyModuleId === module.id && selectedPolicyModule"
                    :class="['module-breakdown-panel', 'inline-module-breakdown', module.tone]"
                  >
                    <div class="module-breakdown-heading">
                      <div :class="['module-breakdown-icon', selectedPolicyModule.tone]">
                        <component :is="selectedPolicyModule.icon" :size="19" />
                      </div>
                      <div>
                        <small>Atomic decomposition · {{ selectedPolicyModule.stageRange }}</small>
                        <h4>{{ selectedPolicyModule.label }}</h4>
                        <p>{{ selectedPolicyModule.expectedChange }}</p>
                      </div>
                      <div class="module-breakdown-stats">
                        <span><b>{{ selectedPolicyModule.instrumentCount }}</b><small>Atomic tools</small></span>
                        <span><b>{{ selectedPolicyModule.typeCount }}</b><small>Tool types</small></span>
                        <span><b>{{ selectedPolicyModule.evidenceCount }}</b><small>Evidence</small></span>
                      </div>
                      <button class="icon-button" type="button" aria-label="Close module detail" @click="collapsePolicyModule">
                        <X :size="17" />
                      </button>
                    </div>

                    <div class="bundle-map-toolbar atomic-detail-toolbar">
                      <div class="bundle-view-switch" role="group" aria-label="Atomic instrument view">
                        <button
                          type="button"
                          :class="{ active: policyInterventionMapMode === 'package' }"
                          @click="policyInterventionMapMode = 'package'"
                        >
                          <Layers3 :size="14" />
                          All Instruments
                        </button>
                        <button
                          type="button"
                          :disabled="!selectedPolicyInterventionNode"
                          :class="{ active: policyInterventionMapMode === 'path' }"
                          @click="policyInterventionMapMode = 'path'"
                        >
                          <Workflow :size="14" />
                          Selected Path
                        </button>
                      </div>
                      <div class="bundle-type-legend" aria-label="Policy intervention type legend">
                        <span v-for="type in policyInterventionTypeLegend" :key="type.id" :class="type.tone">
                          <i></i>{{ type.shortLabel }}
                        </span>
                      </div>
                    </div>

                    <div class="policy-bundle-map module-detail-map">
                      <div
                        class="module-detail-map-canvas"
                        :style="{
                          height: `${policyModuleDetailGeometry.height}px`,
                          '--module-row-height': `${selectedPolicyModule.rowHeight}px`
                        }"
                      >
                        <div class="bundle-map-header">
                          <div class="bundle-axis-label">
                            <small>Selected module</small>
                            <b>Atomic instruments</b>
                          </div>
                          <div v-for="(stage, index) in policyProcessStages" :key="`detail-${stage.id}`" class="bundle-stage-heading">
                            <span>{{ String(index + 1).padStart(2, "0") }}</span>
                            <b>{{ stage.label }}</b>
                            <small>{{ stage.description }}</small>
                          </div>
                        </div>

                        <svg
                          class="module-detail-relation-layer"
                          :viewBox="`0 0 ${policyModuleDetailGeometry.width} ${policyModuleDetailGeometry.height}`"
                          aria-hidden="true"
                        >
                          <defs>
                            <marker id="module-arrowhead" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                              <path d="M0,0 L7,3.5 L0,7 Z"></path>
                            </marker>
                            <marker id="module-arrowhead-active" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                              <path d="M0,0 L7,3.5 L0,7 Z"></path>
                            </marker>
                          </defs>
                          <g
                            v-for="relation in expandedPolicyModuleInternalRelations"
                            :key="`module-relation-${relation.source}-${relation.target}`"
                            :class="[
                              'atomic-relation',
                              `relation-${relation.type.toLowerCase()}`,
                              {
                                active: isPolicyRelationActive(relation),
                                muted: policyInterventionMapMode === 'path' && !isPolicyRelationActive(relation)
                              }
                            ]"
                          >
                            <path
                              :d="policyModuleDetailRelationPath(relation)"
                              :marker-end="isPolicyRelationActive(relation) ? 'url(#module-arrowhead-active)' : 'url(#module-arrowhead)'"
                            ></path>
                            <text
                              v-if="isPolicyRelationActive(relation)"
                              :x="policyModuleDetailRelationLabelPosition(relation).x"
                              :y="policyModuleDetailRelationLabelPosition(relation).y"
                            >
                              {{ relation.type }}
                            </text>
                          </g>
                        </svg>

                        <div class="bundle-swimlane module-detail-swimlane">
                          <div :class="['bundle-module-label', { gap: selectedPolicyModule.gap }]">
                            <span>{{ selectedPolicyModule.index }}</span>
                            <div>
                              <b>{{ selectedPolicyModule.label }}</b>
                              <small>{{ selectedPolicyModule.description }}</small>
                              <em v-if="selectedPolicyModule.gap">Coverage gap</em>
                              <em v-else>{{ selectedPolicyModule.selectedCount }}/{{ selectedPolicyModule.instrumentCount }} confirmed</em>
                            </div>
                          </div>
                          <div
                            v-for="stage in policyProcessStages"
                            :key="`expanded-${selectedPolicyModule.id}-${stage.id}`"
                            :class="[
                              'bundle-stage-cell',
                              {
                                dense: policyNodesForExpandedStage(stage.id).length > 1,
                                empty: policyNodesForExpandedStage(stage.id).length === 0
                              }
                            ]"
                          >
                            <article
                              v-for="node in policyNodesForExpandedStage(stage.id)"
                              :key="`expanded-node-${node.id}`"
                              :class="[
                                'bundle-instrument-node',
                                node.tone,
                                {
                                  selected: selectedPolicyInstrumentId === node.id,
                                  included: node.selected,
                                  muted: isPolicyInterventionNodeMuted(node.id)
                                }
                              ]"
                              role="button"
                              tabindex="0"
                              @click="selectPolicyInstrument(node.id)"
                              @keydown.enter.prevent="selectPolicyInstrument(node.id)"
                            >
                              <div class="bundle-node-type">
                                <component :is="node.icon" :size="12" />
                                <span>{{ node.familyShort }}</span>
                                <button
                                  type="button"
                                  :aria-label="`${node.selected ? 'Exclude' : 'Include'} ${node.instrument}`"
                                  @click.stop="toggleAtomicInstrument(node.id)"
                                >
                                  <CheckCircle2 v-if="node.selected" :size="14" />
                                  <Plus v-else :size="14" />
                                </button>
                              </div>
                              <b>{{ node.instrument }}</b>
                              <small>{{ node.rule.before }} → {{ node.rule.after }}{{ node.rule.unit ? ` ${policyUi(node.rule.unit)}` : "" }}</small>
                              <div class="atomic-node-meta">
                                <span>{{ node.clauseId }}</span>
                                <em>{{ node.rule.confidence }}</em>
                                <i v-if="node.secondaryFamily">+ {{ node.secondaryFamily }}</i>
                              </div>
                            </article>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div class="module-relation-summary">
                      <div>
                        <b>Instrument relations</b>
                        <small>Internal dependencies and connections to other intervention modules.</small>
                      </div>
                      <span v-if="expandedPolicyModuleRelations.length === 0" class="module-relation-empty">
                        No explicit instrument relation is mapped for this module.
                      </span>
                      <template v-else>
                        <span
                          v-for="relation in expandedPolicyModuleRelations"
                          :key="`relation-summary-${relation.source}-${relation.target}`"
                          class="module-relation-item"
                        >
                          <b>{{ relation.sourceLabel }}</b>
                          <em>{{ relation.type }}</em>
                          <ArrowRight :size="13" />
                          <b>{{ relation.targetLabel }}</b>
                          <small>{{ expandedPolicyModuleInternalRelations.includes(relation) ? "Within module" : "Cross-module" }}</small>
                        </span>
                      </template>
                    </div>

                  </section>
                      </template>
                    </div>
                  </div>
                </section>

                  <section class="mapping-integrity-strip">
                    <div>
                      <CheckCircle2 :size="18" />
                      <span><b>Mapping Integrity</b><small>Only confirmed, quantified instruments continue to scenario composition.</small></span>
                    </div>
                    <span><strong>{{ activePolicyLogicCoverage }}%</strong><small>Instrument coverage</small></span>
                    <span><strong>{{ activePolicyMappedVariableCount }}</strong><small>Direct variables</small></span>
                    <span><strong>{{ activePolicyReviewAssumptionCount }}</strong><small>Assumptions to review</small></span>
                    <span><strong>{{ activeMappingPolicy.clauses.length }}</strong><small>Source clauses</small></span>
                  </section>

              </div>
            </section>
          </div>
        </template>

        <template v-else-if="policyMappingTab === 'wizard'">
          <div class="mapping-wizard-grid">
            <section class="panel mapping-draft-panel">
              <div class="panel-header">
                <div>
                  <h2>Create / Adjust Mapping</h2>
                  <p>Structure policy evidence, quantify intervention paths, and compose comparable simulation packages.</p>
                </div>
                <span class="status-pill online">Draft Saved</span>
              </div>
              <label class="mapping-draft-field">
                <span>Policy Text / Policy Concept</span>
                <textarea v-model="mappingDraftText" rows="8"></textarea>
              </label>
              <div class="mapping-draft-meta">
                <label><span>Project</span><input value="Deepen Hong Kong-Macao Cooperation Policy Simulation" /></label>
                <label><span>Study Region</span><input value="Greater Bay Area" /></label>
                <label><span>Simulation Horizon</span><input value="36 months" /></label>
              </div>
            </section>

            <section class="panel mapping-process-panel">
              <div class="panel-header compact">
                <h2>Mapping Process</h2>
                <button class="primary-button" type="button" @click="openMappingTab('scenarios')">
                  <Layers3 :size="16" />Compose Scenarios
                </button>
              </div>
              <div class="wizard-step-stack">
                <article v-for="(step, index) in mappingWizardSteps" :key="step.title">
                  <span>{{ index + 1 }}</span>
                  <div>
                    <b>{{ policyUi(step.title) }}</b>
                    <p>{{ policyUi(step.description) }}</p>
                    <div class="wizard-output-tags">
                      <em v-for="tag in step.outputs" :key="tag">{{ policyUi(tag) }}</em>
                    </div>
                  </div>
                </article>
              </div>
            </section>

            <aside class="panel mapping-mechanism-panel">
              <div class="panel-header compact">
                <h2>Identified Targets & Mechanisms</h2>
                <Info :size="17" />
              </div>
              <div class="mechanism-review-list">
                <article v-for="mechanism in activeMappingPolicy.mechanisms" :key="`wizard-${mechanism.name}`">
                  <b>{{ policyUi(mechanism.name) }}</b>
                  <p>{{ policyUi(mechanism.description) }}</p>
                  <span>{{ policyUi(mechanism.target) }}</span>
                </article>
              </div>
              <div class="mapping-check-card">
                <Shield :size="18" />
                <div>
                  <b>Confirm Scenarios Before Rule Conversion</b>
                  <p>Macro variables do not all enter simulation directly. Assumptions and sensitive variables enter expert review first.</p>
                </div>
              </div>
            </aside>
          </div>
        </template>

        <template v-else-if="policyMappingTab === 'scenarios'">
          <div
            :class="[
              'scenario-confirmation-grid',
              {
                'review-mode': policyMappingWorkflowStep === 'review',
                'design-mode': policyMappingWorkflowStep !== 'review' && policyExperimentDesignStage !== 'generated'
              }
            ]"
          >
            <section class="panel scenario-package-panel experiment-design-panel">
              <div class="panel-header">
                <div>
                  <h2>{{ policyMappingWorkflowStep === "review" ? "Review & Simulation Handoff" : "Scenario Design & Generation" }}</h2>
                  <p>
                    {{
                      policyMappingWorkflowStep === "review"
                        ? "Validate each execution pathway, resolve sensitive assumptions, and freeze the scenario portfolio for simulation."
                        : "Turn a research question into curated policy execution plans and comparison-ready simulation scenarios."
                    }}
                  </p>
                </div>
                <button
                  v-if="policyMappingWorkflowStep === 'review' || policyExperimentDesignStage === 'generated'"
                  class="primary-button"
                  type="button"
                  @click="policyMappingWorkflowStep === 'review' ? openMappingTab('rules') : openMappingWorkflowStep('review')"
                >
                  <ArrowRight :size="16" />{{ policyMappingWorkflowStep === "review" ? "Generate Scenario Package" : "Review Scenario Portfolio" }}
                </button>
              </div>
              <template v-if="policyMappingWorkflowStep !== 'review'">
                <section v-if="policyExperimentDesignStage === 'question'" class="scenario-question-workspace">
                  <div class="scenario-question-editor">
                    <header class="scenario-question-heading">
                      <div>
                        <small>Research question</small>
                        <h3>Choose the decision this simulation should support</h3>
                      </div>
                    </header>
                    <div class="scenario-question-field">
                      <span>Selected question</span>
                      <div :class="['scenario-question-combobox', { open: policyExperimentPresetOpen }]" @keydown.esc.stop="policyExperimentPresetOpen = false">
                        <textarea
                          v-model="policyExperimentQuestionDraft"
                          class="experiment-question-input"
                          rows="4"
                          aria-label="Policy research objective"
                          placeholder="Describe the implementation choices, behavior assumptions, or risks you want to compare."
                        ></textarea>
                        <div class="scenario-question-controlbar">
                          <span>Custom question</span>
                          <button
                            type="button"
                            :aria-expanded="policyExperimentPresetOpen"
                            aria-controls="policy-question-presets"
                            @click="policyExperimentPresetOpen = !policyExperimentPresetOpen"
                          >
                            <Sparkles :size="13" />Recommended questions
                            <ChevronDown :class="{ rotated: policyExperimentPresetOpen }" :size="14" />
                          </button>
                        </div>
                        <div v-if="policyExperimentPresetOpen" id="policy-question-presets" class="scenario-question-preset-menu" role="listbox">
                          <header>
                            <div><small>Policy-specific presets</small><b>Choose a research question</b></div>
                            <span>{{ policyExperimentQuestionExamples.length }} options</span>
                          </header>
                          <button
                            v-for="(example, index) in policyExperimentQuestionExamples"
                            :key="example.key"
                            type="button"
                            role="option"
                            :aria-selected="policyExperimentQuestionDraft.trim() === example.question"
                            :class="{ active: policyExperimentQuestionDraft.trim() === example.question }"
                            @click="applyPolicyExperimentQuestionExample(example.question)"
                          >
                            <span>0{{ index + 1 }}</span>
                            <div><b>{{ example.label }}</b><small>{{ example.question }}</small></div>
                            <CheckCircle2 v-if="policyExperimentQuestionDraft.trim() === example.question" :size="15" />
                            <ArrowRight v-else :size="15" />
                          </button>
                        </div>
                      </div>
                    </div>
                    <div class="scenario-question-actions">
                      <button class="primary-button" type="button" @click="generatePolicyExperimentCandidates">
                        <Sparkles :size="16" />Generate editable experiment plan
                      </button>
                    </div>
                  </div>
                </section>

                <section v-else-if="policyExperimentDesignStage === 'curate'" class="scenario-plan-workspace">
                  <div class="scenario-plan-questionbar">
                    <Target :size="16" />
                    <div>
                      <small>Research question</small>
                      <p>{{ policyExperimentAppliedObjective }}</p>
                    </div>
                    <button class="ghost-button" type="button" @click="returnToPolicyExperimentQuestion">Revise</button>
                  </div>
                  <header class="scenario-plan-heading">
                    <div>
                      <small>Generated text draft</small>
                      <h3>Edit the comparison logic directly</h3>
                      <p>Each numbered statement becomes one policy experiment. Rewrite, remove, or add a statement before generating the detailed scenarios.</p>
                    </div>
                    <div>
                      <span>{{ policyExperimentCandidateDrafts.length }} logic statements</span>
                      <button class="ghost-button" type="button" @click="addPolicyExperimentCandidate"><Plus :size="15" />Add logic</button>
                    </div>
                  </header>

                  <section class="scenario-logic-editor">
                    <header>
                      <div><small>Editable experiment logic</small><h4>Policy execution pathways to compare</h4></div>
                      <span>A shared current-practice baseline is added automatically.</span>
                    </header>
                    <ol>
                      <li
                        v-for="(candidate, index) in policyExperimentCandidateDrafts"
                        :key="candidate.key"
                        :class="candidate.tone"
                      >
                        <span class="scenario-logic-index">{{ String(index + 1).padStart(2, "0") }}</span>
                        <div class="scenario-logic-copy">
                          <input v-model="candidate.name" :aria-label="`Logic ${index + 1} title`" />
                          <textarea v-model="candidate.narrative" rows="2" :aria-label="`Logic ${index + 1} description`"></textarea>
                        </div>
                        <button class="icon-button" type="button" title="Remove logic" @click="removePolicyExperimentCandidate(candidate.key)"><Trash2 :size="14" /></button>
                      </li>
                    </ol>
                  </section>

                  <footer class="scenario-plan-confirmation">
                    <div>
                      <FileText :size="17" />
                      <p><b>Confirm these statements before generating detailed scenarios.</b><span>{{ policyExperimentCandidateDrafts.length }} statements plus one shared baseline will become {{ policyExperimentCandidateDrafts.length + 1 }} comparable runs.</span></p>
                    </div>
                    <div>
                      <button class="ghost-button" type="button" @click="returnToPolicyExperimentQuestion">Revise question</button>
                      <button class="primary-button" type="button" :disabled="!policyExperimentCandidateDrafts.length" @click="confirmPolicyExperimentCandidates">
                        Generate detailed simulation scenarios <ArrowRight :size="15" />
                      </button>
                    </div>
                  </footer>
                </section>

                <template v-else>
                  <div class="scenario-generated-brief">
                    <div>
                      <small>Confirmed research question</small>
                      <p>{{ policyExperimentAppliedObjective }}</p>
                    </div>
                    <span><b>{{ policyExperimentSuiteSummary.runs }}</b> model-ready runs</span>
                    <span><b>{{ policyExperimentSuiteSummary.contrasts }}</b> planned contrasts</span>
                    <button class="ghost-button" type="button" @click="editPolicyExperimentPlans"><SlidersHorizontal :size="15" />Edit plan set</button>
                  </div>

                  <div class="experiment-suite-heading">
                    <div>
                      <h3>Generated Simulation Scenario Portfolio</h3>
                      <p>{{ policyExperimentAppliedPlan || "The confirmed plan is translated into a shared baseline, policy combinations, response assumptions, and comparison contracts." }}</p>
                    </div>
                    <span>Portfolio v{{ policyExperimentGenerationVersion }} · Confirmed</span>
                  </div>

                  <div class="policy-experiment-grid">
                    <button
                      v-for="experiment in policyExperimentScenarios"
                      :key="experiment.id"
                      :class="['policy-experiment-card', experiment.tone, { selected: selectedPolicyExperimentId === experiment.id }]"
                      type="button"
                      @click="selectPolicyExperimentScenario(experiment.id)"
                    >
                      <div class="experiment-card-head">
                        <span class="experiment-run-id">{{ experiment.id }}</span>
                        <span :class="['experiment-role-pill', experiment.tone]">{{ experiment.type }}</span>
                        <CheckCircle2 v-if="selectedPolicyExperimentId === experiment.id" :size="17" />
                      </div>
                      <h3>{{ experiment.name }}</h3>
                      <p>{{ experiment.narrative }}</p>
                      <div class="experiment-profile-brief">
                        <span><small>Coverage</small>{{ experiment.coverage }}</span>
                        <span><small>Firm response</small>{{ experiment.enterpriseResponse }}</span>
                      </div>
                      <div class="experiment-card-section">
                        <small>Policy combination</small>
                        <div class="experiment-package-chips">
                          <em v-if="!experiment.packageNames.length">No new policy package</em>
                          <em v-for="packageName in experiment.packageNames" :key="packageName">{{ packageName }}</em>
                        </div>
                      </div>
                      <div class="experiment-feedback-line">
                        <Network :size="14" />
                        <span>{{ experiment.deliveryMode }} · {{ experiment.rolloutTiming }}</span>
                      </div>
                      <div class="experiment-card-footer">
                        <span>{{ experiment.contrast }}</span>
                        <b>{{ experiment.compareTo }}</b>
                      </div>
                    </button>
                  </div>

                  <div class="experiment-contrast-block">
                    <div class="experiment-suite-heading compact">
                      <div>
                        <h3>Scenario Comparison Logic</h3>
                        <p>Every contrast now corresponds to a user-confirmed implementation choice.</p>
                      </div>
                    </div>
                    <div class="experiment-contrast-table">
                      <div class="experiment-contrast-head">
                        <span>Scenario</span><span>Compared with</span><span>What changes</span><span>Decision readout</span>
                      </div>
                      <button
                        v-for="row in policyExperimentComparisonRows"
                        :key="`contrast-${row.id}`"
                        :class="{ selected: selectedPolicyExperimentId === row.id }"
                        type="button"
                        @click="selectPolicyExperimentScenario(row.id)"
                      >
                        <span><b>{{ row.id }}</b>{{ row.name }}</span>
                        <code>{{ row.calculation }}</code>
                        <strong>{{ row.isolates }}</strong>
                        <span>{{ row.readout }}</span>
                      </button>
                    </div>
                  </div>
                </template>
              </template>

              <div v-else class="experiment-review-stack">
                <div class="experiment-review-summary">
                  <span><b>{{ policyExperimentSuiteSummary.runs }}</b> execution scenarios</span>
                  <span><b>{{ policyExperimentSuiteSummary.contrasts }}</b> planned comparisons</span>
                  <span><b>{{ policyExperimentSuiteSummary.uniqueRules }}</b> available atomic rules</span>
                  <span><b>{{ activeMappingPolicy.reviewItems.length }}</b> policy-level review items</span>
                </div>
                <div class="experiment-review-list">
                  <button
                    v-for="experiment in policyExperimentScenarios"
                    :key="`review-${experiment.id}`"
                    :class="[experiment.tone, { selected: selectedPolicyExperimentId === experiment.id }]"
                    type="button"
                    @click="selectPolicyExperimentScenario(experiment.id)"
                  >
                    <span class="experiment-run-id">{{ experiment.id }}</span>
                    <div>
                      <b>{{ experiment.name }}</b>
                      <p>{{ experiment.narrative }}</p>
                    </div>
                    <span>{{ experiment.ruleCount }} rules</span>
                    <span>{{ experiment.enterpriseResponse }}</span>
                    <code>{{ experiment.contrast }}</code>
                    <span :class="['mapping-status', experiment.reviewCount ? 'review' : 'ready']">
                      {{ experiment.reviewCount ? `${experiment.reviewCount} to review` : "Ready" }}
                    </span>
                  </button>
                </div>
                <div class="review-queue-stack">
                  <article v-for="item in activeMappingPolicy.reviewItems" :key="`review-main-${item.title}`" :class="item.tone">
                    <AlertTriangle :size="18" />
                    <div>
                      <b>{{ policyUi(item.title) }}</b>
                      <p>{{ policyUi(item.detail) }}</p>
                      <div class="review-action-row">
                        <button type="button">Confirm</button>
                        <button type="button">Edit</button>
                        <button type="button">Request Data</button>
                      </div>
                    </div>
                  </article>
                </div>
              </div>
            </section>

            <div v-if="policyMappingWorkflowStep === 'review' || policyExperimentDesignStage === 'generated'" class="scenario-side-stack">
              <section class="panel scenario-detail-panel experiment-detail-panel">
                <div class="panel-header compact">
                  <div>
                    <small>Selected execution scenario</small>
                    <h2>{{ selectedPolicyExperiment.name }}</h2>
                  </div>
                  <span :class="['experiment-role-pill', selectedPolicyExperiment.tone]">{{ selectedPolicyExperiment.id }}</span>
                </div>
                <div class="experiment-detail-intent">
                  <span>{{ selectedPolicyExperiment.type }}</span>
                  <p>{{ selectedPolicyExperiment.narrative }}</p>
                  <p>{{ selectedPolicyExperiment.hypothesis }}</p>
                </div>
                <div class="experiment-scenario-profile">
                  <article><small>Coverage</small><b>{{ selectedPolicyExperiment.coverage }}</b></article>
                  <article><small>Delivery</small><b>{{ selectedPolicyExperiment.deliveryMode }}</b></article>
                  <article><small>Enterprise response</small><b>{{ selectedPolicyExperiment.enterpriseResponse }}</b></article>
                  <article><small>Timing</small><b>{{ selectedPolicyExperiment.rolloutTiming }}</b></article>
                </div>
                <div class="experiment-detail-section">
                  <h3>Policy combination</h3>
                  <article v-if="!selectedPolicyExperiment.packageDetails.length" class="experiment-empty-combination">
                    <Database :size="16" />
                    <span>No new policy rules; current model configuration is preserved.</span>
                  </article>
                  <article v-for="item in selectedPolicyExperiment.packageDetails" :key="`selected-${item.id}`">
                    <div>
                      <b>{{ item.name }}</b>
                      <span>{{ item.strength }} intensity</span>
                    </div>
                    <strong>{{ item.ruleCount }} rules</strong>
                  </article>
                </div>
                <div class="experiment-detail-section feedback">
                  <h3>Behavior & feedback assumptions</h3>
                  <p v-for="condition in selectedPolicyExperiment.feedback" :key="condition">
                    <CheckCircle2 :size="14" />{{ condition }}
                  </p>
                </div>
                <div class="experiment-detail-contrast">
                  <span>Planned comparison</span>
                  <code>{{ selectedPolicyExperiment.contrast }}</code>
                  <b>{{ selectedPolicyExperiment.compareTo }}</b>
                </div>
                <div class="experiment-detail-decision">
                  <small>Decision use</small>
                  <p>{{ selectedPolicyExperiment.decisionUse }}</p>
                </div>
                <div class="scenario-review-actions">
                  <button
                    class="primary-button"
                    type="button"
                    @click="policyMappingWorkflowStep === 'review' ? openMappingTab('rules') : openMappingWorkflowStep('review')"
                  >
                    {{ policyMappingWorkflowStep === "review" ? "Approve Portfolio" : "Review Scenario Portfolio" }}
                  </button>
                </div>
              </section>

              <aside class="panel scenario-risk-panel experiment-contract-panel">
                <div class="panel-header compact">
                  <h2>{{ policyMappingWorkflowStep === "review" ? "Simulation Handoff Gate" : "Result Comparison Contract" }}</h2>
                  <span class="count-pill">{{ policyMappingWorkflowStep === "review" ? activeMappingPolicy.reviewItems.length : selectedPolicyExperiment.primaryMetrics.length }}</span>
                </div>
                <div v-if="policyMappingWorkflowStep !== 'review'" class="experiment-readout-list">
                  <article>
                    <small>Primary readout</small>
                    <p>{{ selectedPolicyExperiment.resultReadout }}</p>
                  </article>
                  <article>
                    <small>Primary metrics</small>
                    <div>
                      <span v-for="metric in selectedPolicyExperiment.primaryMetrics" :key="metric">{{ metric }}</span>
                    </div>
                  </article>
                  <article class="guardrail">
                    <small>Guardrail</small>
                    <p>{{ selectedPolicyExperiment.guardrail }}</p>
                  </article>
                </div>
                <div v-else class="confirmation-rule-list">
                  <article>
                    <b>Comparison integrity</b>
                    <p>All scenarios use the same initial population, random seeds, simulation horizon, and metric definitions.</p>
                  </article>
                  <article>
                    <b>Parameter confirmation</b>
                    <p>Scenario assumptions and expert-set parameters require an evidence or approval record before handoff.</p>
                  </article>
                  <article>
                    <b>Run manifest</b>
                    <p>Each scenario stores its policy combination, rollout scope, response assumptions, comparison target, and decision readout.</p>
                  </article>
                </div>
                <div class="mapping-check-card">
                  <Database :size="18" />
                  <div>
                    <b>Common measurement contract</b>
                    <p>Every scenario reports the same outcomes, guardrails, and period windows so implementation differences remain interpretable.</p>
                  </div>
                </div>
              </aside>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="atomic-rule-grid">
            <section class="panel atomic-rule-panel">
              <header class="atomic-rule-header">
                <div class="atomic-rule-title">
                  <small>Step 4 output · {{ selectedPolicyExperiment.id }} selected</small>
                  <h2>Simulation Scenario Package</h2>
                  <p>A comparison-ready portfolio with one model configuration for each policy execution pathway.</p>
                </div>
                <div class="atomic-rule-actions">
                  <button class="ghost-button" type="button"><Copy :size="15" />Copy manifest</button>
                  <button class="primary-button" type="button"><Package :size="15" />Simulation config</button>
                </div>
              </header>

              <div class="experiment-output-selector" aria-label="Policy implementation scenarios">
                <button
                  v-for="experiment in policyExperimentScenarios"
                  :key="`output-${experiment.id}`"
                  :class="[experiment.tone, { selected: selectedPolicyExperimentId === experiment.id }]"
                  type="button"
                  @click="selectPolicyExperimentScenario(experiment.id)"
                >
                  <span>{{ experiment.id }}</span>
                  <div><b>{{ experiment.name }}</b><small>{{ experiment.contrast }}</small></div>
                  <em>{{ experiment.ruleCount }} rules</em>
                </button>
              </div>

              <div class="atomic-rule-summary" aria-label="Simulation scenario package summary">
                <span><b>{{ policyExperimentSuiteSummary.runs }}</b><small>Scenario runs</small></span>
                <span><b>{{ atomicRulePackageSummary.total }}</b><small>Selected rules</small></span>
                <span><b>{{ atomicRulePackageSummary.confirmed }}</b><small>Source-backed</small></span>
                <span><b>{{ atomicRulePackageSummary.review }}</b><small>Need review</small></span>
                <span><b>{{ atomicRulePackageSummary.modules }}</b><small>Model targets</small></span>
              </div>

              <div v-if="activeAtomicRuleRows.length" class="atomic-rule-ledger">
                <div class="atomic-rule-ledger-head">
                  <span>Rule</span>
                  <span>Value change</span>
                  <span>Package</span>
                  <span>Evidence</span>
                  <span>Model target</span>
                  <span>Review</span>
                </div>
                <div
                  v-for="rule in activeAtomicRuleRows"
                  :key="`${rule.packageId || 'base'}-${rule.id}`"
                  :class="[
                    'atomic-rule-ledger-row',
                    rule.statusTone,
                    {
                      custom: rule.customized,
                      selected: selectedAtomicRulePreview?.id === rule.id
                    }
                  ]"
                  role="button"
                  tabindex="0"
                  @click="selectAtomicRulePreview(rule.id)"
                  @keydown.enter.prevent="selectAtomicRulePreview(rule.id)"
                  @keydown.space.prevent="selectAtomicRulePreview(rule.id)"
                >
                  <span class="atomic-rule-identity">
                    <b>{{ policyUi(rule.name) }}</b>
                    <code>{{ rule.id }}</code>
                  </span>
                  <span class="atomic-rule-value">
                    <b>{{ rule.before }}</b>
                    <ArrowRight :size="13" aria-hidden="true" />
                    <strong>{{ rule.after }}{{ rule.unit ? ` ${policyUi(rule.unit)}` : "" }}</strong>
                  </span>
                  <span class="atomic-rule-package">
                    <b>{{ policyUi(rule.packageName || "Base policy") }}</b>
                    <small>{{ policyUi(rule.strength || "Default") }}</small>
                  </span>
                  <span class="atomic-rule-evidence">
                    <b>{{ policyUi(rule.source) }}</b>
                    <small>{{ rule.customized ? "Pending validation" : `Confidence ${rule.confidence}` }}</small>
                  </span>
                  <span class="atomic-rule-target">{{ policyUi(rule.module) }}</span>
                  <span :class="['mapping-status', rule.statusTone]">{{ policyUi(rule.status) }}</span>
                </div>
              </div>
              <div v-else class="atomic-rule-empty">
                <Database :size="22" />
                <div>
                  <b>Control run preserves the current model state</b>
                  <p>No new atomic rule is applied in {{ selectedPolicyExperiment.id }}. This scenario provides the common counterfactual for all policy comparisons.</p>
                </div>
              </div>

              <footer v-if="selectedAtomicRulePreview" class="atomic-rule-diff">
                <div class="atomic-rule-diff-key">
                  <span><FileCog :size="14" />Selected payload change</span>
                  <code>{{ selectedAtomicRulePreview.id }}</code>
                </div>
                <div class="atomic-rule-diff-values" aria-label="Selected rule value change">
                  <code class="before"><i>−</i>{{ selectedAtomicRulePreview.before }}</code>
                  <ArrowRight :size="13" aria-hidden="true" />
                  <code class="after">
                    <i>+</i>{{ selectedAtomicRulePreview.after }}{{ selectedAtomicRulePreview.unit ? ` ${policyUi(selectedAtomicRulePreview.unit)}` : "" }}
                  </code>
                </div>
                <div class="atomic-rule-diff-meta">
                  <b>{{ policyUi(selectedAtomicRulePreview.source) }}</b>
                  <small>{{ selectedAtomicRulePreview.customized ? "Pending validation" : `Confidence ${selectedAtomicRulePreview.confidence}` }}</small>
                </div>
              </footer>
            </section>

            <aside class="panel package-impact-panel atomic-handoff-panel">
              <header class="atomic-handoff-header">
                <div>
                  <small>Agent handoff</small>
                  <h2>Model Linkage</h2>
                  <p>Where selected rules enter the simulation model.</p>
                </div>
                <span :class="['mapping-status', atomicRulePackageSummary.review ? 'review' : 'ready']">
                  {{ atomicRulePackageSummary.review ? `${atomicRulePackageSummary.review} to review` : "Ready" }}
                </span>
              </header>

              <div class="atomic-handoff-scroll">
                <section class="atomic-handoff-overview">
                  <div class="atomic-linkage-flow" aria-label="Rule to agent handoff flow">
                    <article>
                      <small>01</small>
                      <div><b>Policy rules</b><span>Selected inputs</span></div>
                      <strong>{{ atomicRulePackageSummary.total }}</strong>
                    </article>
                    <ArrowRight :size="14" aria-hidden="true" />
                    <article>
                      <small>02</small>
                      <div><b>Model targets</b><span>Variables and modules</span></div>
                      <strong>{{ atomicRulePackageSummary.modules }}</strong>
                    </article>
                    <ArrowRight :size="14" aria-hidden="true" />
                    <article>
                      <small>03</small>
                      <div><b>Agent surfaces</b><span>Decision locations</span></div>
                      <strong>{{ atomicModelSurfaceRows.length }}</strong>
                    </article>
                  </div>
                  <div class="atomic-review-progress">
                    <span>
                      <b>Evidence confirmed</b>
                      <small>{{ atomicRulePackageSummary.confirmed }} of {{ atomicRulePackageSummary.total }} rules</small>
                    </span>
                    <strong>{{ atomicHandoffConfirmationRate }}%</strong>
                    <div><i :style="{ width: `${atomicHandoffConfirmationRate}%` }"></i></div>
                  </div>
                </section>

                <section class="atomic-handoff-section">
                  <h3>Affected model surfaces</h3>
                  <div class="model-linkage-list">
                    <article v-for="surface in atomicModelSurfaceRows" :key="surface.key" :class="surface.key">
                      <span><component :is="surface.icon" :size="17" /></span>
                      <div>
                        <b>{{ surface.label }}</b>
                        <small>{{ surface.description }}</small>
                      </div>
                      <em>{{ surface.linkedRules }} rules</em>
                    </article>
                  </div>
                </section>

                <section class="atomic-handoff-section">
                  <div class="atomic-section-heading">
                    <h3>Expected response</h3>
                    <small>Scenario estimate</small>
                  </div>
                  <div class="handoff-impact-list">
                    <article v-for="impact in atomicExpectedResponseRows" :key="impact.label">
                      <span>
                        <span>
                          <b>{{ policyUi(impact.label) }}</b>
                          <small>Primary driver · {{ impact.driver }}</small>
                        </span>
                        <strong>{{ impact.delta }}</strong>
                      </span>
                      <div><i :style="{ width: impact.width }"></i></div>
                    </article>
                  </div>
                </section>

                <section class="atomic-handoff-section">
                  <h3>Evaluation readiness</h3>
                  <div class="atomic-readiness-list">
                    <article v-for="item in policyEvaluationReadiness" :key="item.title">
                      <div><b>{{ policyUi(item.title) }}</b><small>{{ policyUi(item.detail) }}</small></div>
                      <strong>{{ policyUi(item.value) }}</strong>
                    </article>
                  </div>
                </section>

                <div v-if="atomicRulePackageSummary.review" class="atomic-handoff-next">
                  <AlertTriangle :size="16" />
                  <div>
                    <b>Next action</b>
                    <p>Confirm {{ atomicRulePackageSummary.review }} inferred or expert-set parameters before the final simulation handoff.</p>
                  </div>
                </div>
              </div>
            </aside>
          </div>
        </template>
      </section>

      <section v-else-if="activeView === 'workflow'" class="workflow-page workflow-builder-page">
        <div class="workflow-top-toolbar">
          <section class="panel workflow-overview-card workflow-configuration-card">
            <div class="workflow-panel-title compact">
              <h2>Configuration Overview</h2>
              <p>Scenario, cadence, agent source, and network prior.</p>
            </div>
            <div class="workflow-configuration-body">
              <div class="workflow-configuration-grid">
                <label class="workflow-select-control">
                  <Globe2 :size="17" />
                  <select v-model="selectedCluster">
                    <option v-for="cluster in clusterRows" :key="cluster.name" :value="cluster.name">{{ cluster.name }}</option>
                  </select>
                  <ChevronDown :size="16" />
                </label>
                <label class="workflow-config-field">
                  <span>Horizon</span>
                  <select v-model.number="workflowHorizonYears">
                    <option v-for="year in workflowYearOptions" :key="year" :value="year">{{ year }} years</option>
                  </select>
                </label>
                <label class="workflow-config-field">
                  <span>Time Step</span>
                  <strong>Monthly</strong>
                </label>
              </div>
              <div class="workflow-config-summary-row">
                <div class="workflow-stat-pill"><Users :size="21" /><b>{{ displayedSimulationAgentCount }}</b><span>Agents</span></div>
                <div class="workflow-stat-pill"><Database :size="21" /><b>{{ useDatabaseAgents ? "Database" : "Default" }}</b><span>Agent Source</span></div>
                <div class="workflow-stat-pill"><MapPin :size="21" /><b>{{ activeCluster.region || "GBA" }}</b><span>Region</span></div>
                <div class="workflow-stat-pill"><Network :size="21" /><b>{{ useDatabaseAgents && usePriorNetworkEdges ? "On" : "Off" }}</b><span>Network Prior</span></div>
              </div>
            </div>
          </section>

          <section class="panel workflow-overview-card workflow-run-card">
            <div class="workflow-run-card-heading">
              <div class="workflow-panel-title compact">
                <h2>Run Simulation</h2>
                <p>Push this workflow into simulation and analytics.</p>
              </div>
              <span :class="['workflow-run-status', workflowRunStatus]">{{ workflowReadinessLabel }}</span>
            </div>
            <div class="workflow-run-card-body">
              <div class="workflow-run-card-main">
                <ProcurementSelector v-model="procurementExecution" :disabled="running" @ready="procurementReady = $event" />
                <fieldset v-if="procurementExecution.mode === 'codedemo_micro'" :disabled="running">
                  <legend>Shared project input</legend>
                  <label>Case ID <input v-model="integrationCaseId" aria-label="Shared case ID" /></label>
                  <label>Model mode <select v-model="integrationModelMode"><option value="llm">Live configured model</option><option value="offline">Offline fixture</option></select></label>
                  <label v-if="integrationModelMode === 'llm'"><input v-model="integrationDataConsent" type="checkbox" /> Allow this run to send the selected project, enterprise descriptions and scenario parameters to the configured model provider.</label>
                  <p>Micro mode uses the shared case database, not the generated enterprise cluster. <a href="/integration" target="_blank">Open the integration workbench for case selection, owner package planning and member discussions.</a></p>
                </fieldset>
                <ProcurementReceipt :simulation-id="simulationId" />
                <div class="workflow-runtime-estimate">
                  <Timer :size="18" />
                  <span>Estimated Runtime</span>
                  <b>~ {{ workflowEstimatedRuntimeMinutes }} min</b>
                  <small>Est. for {{ displayedSimulationAgentCount }} agents</small>
                </div>
                <div class="workflow-run-actions-stack">
                  <div class="workflow-readiness-command-row">
                    <button class="workflow-warning-card" type="button" @click="selectTimelineItem(workflowWarningAnchorId)">
                      <AlertTriangle :size="20" />
                      <span><b>{{ workflowWarningsCount }}</b> warnings</span>
                      <ChevronRight :size="15" />
                    </button>
                    <button class="ghost-button" type="button" @click="saveWorkflowTemplate" :disabled="running">
                      <FolderDown :size="17" />Save
                    </button>
                    <button class="ghost-button" type="button" @click="loadWorkflowTemplate" :disabled="running">
                      <FolderOpen :size="17" />Load
                    </button>
                  </div>
                  <button class="primary-button workflow-run-primary" type="button" :disabled="running || !procurementReady" @click="runSimulation">
                    <Play :size="17" />{{ running ? "Running..." : "Run Simulation" }}
                  </button>
                </div>
                <p v-if="workflowTemplateMessage" :class="['workflow-template-message', workflowTemplateMessageTone]">{{ workflowTemplateMessage }}</p>
                <p v-if="workflowRunError" class="workflow-run-error">{{ workflowRunError }}</p>
              </div>
            </div>
          </section>
        </div>

        <div :class="['workflow-builder-layout', { 'inspector-open': workflowInspectorOpen && selectedTimelineItem }]">
          <div class="workflow-main-stack">
            <section class="panel workflow-timeline-panel">
              <div class="workflow-timeline-heading">
                <div class="workflow-panel-title">
                  <h2>Workflow Timeline</h2>
                  <p>Drag policies and events to reschedule them. Click inside a period to split it, or use a shared boundary to resize or merge.</p>
                </div>
                <div class="workflow-timeline-actions">
                  <button class="policy" type="button" @click="addWorkflowTimelineItem('policy')"><Plus :size="17" />Add Policy</button>
                  <button class="event" type="button" @click="addWorkflowTimelineItem('event')"><Plus :size="17" />Add Event</button>
                </div>
              </div>

              <div class="workflow-timeline-shell">
                <div class="workflow-timeline-side">
                  <div class="months">Months</div>
                  <div class="lane-label phase"><LineChart :size="18" /><b>Periods</b><span>Split · merge · resize</span></div>
                  <div class="lane-label policy"><Shield :size="18" /><b>Policies</b><span>Duration spans</span></div>
                  <div class="lane-label event"><Target :size="18" /><b>Events</b><span>Point in time</span></div>
                </div>
                <div class="workflow-flow-scroll">
                  <div ref="workflowTimelineTrack" class="workflow-flow-track" :style="workflowTimelineTrackStyle">
                    <div class="workflow-flow-row phase"></div>
                    <div class="workflow-flow-row policy"></div>
                    <div class="workflow-flow-row event"></div>
                    <div
                      v-for="tick in timelineScaleTicks"
                      :key="tick.tick"
                      class="workflow-year-tick"
                      :style="{ left: `${tick.percent}%`, '--tick-shift': tick.shift }"
                    >
                      <span>{{ timelineMonthLabel(tick.tick) }}</span>
                    </div>
                    <button
                      v-for="item in workflowTimelineItems"
                      :key="item.id"
                      type="button"
                      :class="[
                        'workflow-flow-node',
                        item.type,
                        {
                          active: selectedTimelineItemId === item.id,
                          dragging: workflowTimelineDragState?.id === item.id,
                          'compact-policy': item.compact,
                          'phase-start': item.type === 'phase' && item.order === 0,
                          'phase-end': item.type === 'phase' && item.order === workflowPeriodRows.length - 1
                        }
                      ]"
                      :style="workflowTimelineItemStyle(item)"
                      :data-timeline-item-id="item.id"
                      :aria-label="`${item.title} ${timelineMonthRangeLabel(item)}`"
                      :title="item.type === 'event' ? 'Drag to change event month' : item.type === 'policy' ? 'Drag to move; use the edge handles to resize' : 'Click inside to split; drag an edge to resize'"
                      @pointerdown="startWorkflowTimelineDrag($event, item, item.type === 'phase' ? 'select' : 'move')"
                      @pointermove="item.type === 'phase' && updateWorkflowPeriodSplitPreview($event, item)"
                      @pointerleave="item.type === 'phase' && clearWorkflowPeriodSplitPreview(item.id)"
                      @click="handleWorkflowTimelineItemClick($event, item)"
                    >
                      <template v-if="item.type === 'event'">
                        <span class="timeline-event-pin" aria-hidden="true"></span>
                        <span class="timeline-event-card">
                          <strong>{{ item.title }}</strong>
                          <small>{{ timelineMonthRangeLabel(item) }}</small>
                        </span>
                      </template>
                      <template v-else>
                        <component :is="timelineItemIcon(item.type)" :size="18" />
                        <strong>{{ item.title }}</strong>
                        <small>{{ timelineMonthRangeLabel(item) }}</small>
                        <span
                          v-if="item.type === 'phase' && workflowPeriodHoverState?.id === item.id"
                          class="timeline-split-preview"
                          :style="workflowPeriodSplitPreviewStyle(item)"
                          aria-hidden="true"
                        >
                          <Scissors :size="12" />
                          <em>M{{ workflowPeriodHoverState.month }}</em>
                        </span>
                      </template>
                      <span
                        v-if="item.type === 'policy'"
                        class="timeline-resize-handle start"
                        title="Drag to adjust start month"
                        aria-hidden="true"
                        @pointerdown.stop.prevent="startWorkflowTimelineDrag($event, item, 'resize-start')"
                      ></span>
                      <span
                        v-if="item.type !== 'event' && (item.type !== 'phase' || item.order < workflowPeriodRows.length - 1)"
                        class="timeline-resize-handle end"
                        title="Drag to adjust end month"
                        aria-hidden="true"
                        @pointerdown.stop.prevent="startWorkflowTimelineDrag($event, item, 'resize-end')"
                      ></span>
                    </button>
                    <button
                      v-for="boundary in workflowPeriodBoundaries"
                      :key="boundary.id"
                      class="timeline-merge-preview"
                      type="button"
                      :style="{ left: `${boundary.percent}%` }"
                      :aria-label="boundary.label"
                      :title="boundary.label"
                      @pointerdown.stop
                      @click.stop="mergeWorkflowPeriodBoundary(boundary)"
                    >
                      <GitMerge :size="13" />
                      <span>{{ boundary.label }}</span>
                    </button>
                  </div>
                  <div class="workflow-scroll-hint">
                    <ChevronLeft :size="14" />
                    <span>Scroll horizontally for longer horizons</span>
                    <ChevronRight :size="14" />
                  </div>
                </div>
              </div>
              <button class="workflow-details-pull-tab" type="button" aria-expanded="false">
                <span class="workflow-details-grip"></span>
                Details
                <ChevronUp :size="12" />
              </button>
            </section>
          </div>

          <aside class="workflow-priority-sidebar">
            <section v-if="selectedTimelineItem" class="panel workflow-inspector-panel">
              <div class="workflow-inspector-heading">
                <span :class="['timeline-detail-icon', selectedTimelineItem.type]">
                  <component :is="timelineItemIcon(selectedTimelineItem.type)" :size="20" />
                </span>
                <div>
                  <small>Selected: <b>{{ selectedTimelineKindLabel }}</b></small>
                  <h2>{{ selectedTimelineItem.title }}</h2>
                  <p>{{ timelineMonthRangeLabel(selectedTimelineItem) }}</p>
                </div>
                <button class="icon-button" type="button" @click="selectedTimelineItemId = ''" aria-label="Close selected workflow item">
                  <X :size="17" />
                </button>
              </div>
              <div class="timeline-detail-grid inspector">
                <label>
                  <span>Name</span>
                  <input
                    :value="selectedTimelineItem.title"
                    @input="updateSelectedTimelineItem({ title: $event.target.value })"
                  />
                </label>
                <label>
                  <span>Start</span>
                  <input
                    type="number"
                    min="0"
                    :max="workflowTicks"
                    :disabled="selectedTimelineItem.type === 'phase' && selectedTimelinePeriodIndex === 0"
                    :value="selectedTimelineItem.startTick"
                    @change="updateSelectedTimelineItem({ startTick: Number($event.target.value) })"
                  />
                </label>
                <label>
                  <span>End</span>
                  <input
                    type="number"
                    min="0"
                    :max="workflowTicks"
                    :disabled="selectedTimelineItem.type === 'event' || (selectedTimelineItem.type === 'phase' && selectedTimelinePeriodIndex === workflowPeriodRows.length - 1)"
                    :value="selectedTimelineItem.endTick"
                    @change="updateSelectedTimelineItem({ endTick: Number($event.target.value) })"
                  />
                </label>
                <label class="timeline-notes-field">
                  <span>Notes</span>
                  <textarea
                    rows="3"
                    :value="selectedTimelineItem.note || ''"
                    placeholder="Add notes for this workflow item"
                    @input="updateSelectedTimelineItem({ note: $event.target.value })"
                  ></textarea>
                </label>
              </div>
              <div class="workflow-duration-row">
                <span>Duration</span>
                <b>{{ selectedTimelineDuration }} months</b>
              </div>
              <div :class="['workflow-danger-row', { single: selectedTimelineItem.type === 'phase' }]">
                <button class="primary-button" type="button" @click="confirmSelectedTimelineItemUpdate">
                  Update
                </button>
                <button v-if="selectedTimelineItem.type !== 'phase'" class="ghost-button danger" type="button" @click="removeSelectedWorkflowTimelineItem" :disabled="!canRemoveSelectedTimelineItem">
                  <Trash2 :size="16" />Delete {{ selectedTimelineKindLabel }}
                </button>
              </div>
            </section>
          </aside>
        </div>
      </section>

      <section v-else-if="activeView === 'simulation'" class="simulation-page">
        <ProcurementReceipt :simulation-id="simulationId" />
        <div class="simulation-workbench">
          <section class="map-panel panel simulation-map-main">
            <div class="map-toolbar">
              <div class="map-title-block">
                <span class="muted">Greater Bay Area map · Project lifecycle playback</span>
                <div class="map-heading-row">
                  <h2>Project and Collaboration Evolution</h2>
                  <div class="map-playback-inline">
                    <div class="playback-track">
                      <div class="playback-track-head">
                        <span>{{ currentStageLabel }}</span>
                        <b>{{ playbackPercent }}%</b>
                      </div>
                      <input
                        v-model.number="currentPlaybackTick"
                        type="range"
                        min="1"
                        :max="playbackMaxTick"
                        :style="{ '--playback-progress': `${playbackPercent}%` }"
                        @change="seekPlaybackTick"
                      />
                    </div>
                    <button class="icon-button playback-button" @click="togglePlayback" :aria-label="simulationPlaying ? 'Pause playback' : 'Play playback'">
                      <component :is="simulationPlaying ? Pause : Play" :size="18" />
                    </button>
                    <button class="ghost-button step-button" @click="stepPlayback(1)">Step <ChevronRight :size="15" /></button>
                    <label class="playback-speed-select" aria-label="Playback speed">
                      <Timer :size="14" />
                      <span>{{ playbackSpeed }}x</span>
                      <ChevronDown :size="13" />
                      <select v-model.number="playbackSpeed">
                        <option v-for="speed in playbackSpeedOptions" :key="speed" :value="speed">{{ speed }}x</option>
                      </select>
                    </label>
                  </div>
                </div>
              </div>
              <div class="map-tool-buttons">
                <button class="icon-button" type="button" title="Zoom out" aria-label="Zoom out" @click="changeRuntimeMapZoom(-0.18)">
                  <ZoomOut :size="17" />
                </button>
                <button class="icon-button" type="button" title="Zoom in" aria-label="Zoom in" @click="changeRuntimeMapZoom(0.18)">
                  <ZoomIn :size="17" />
                </button>
                <button class="icon-button" type="button" title="Reset map" aria-label="Reset map" @click="resetRuntimeMap">
                  <RotateCcw :size="16" />
                </button>
              </div>
            </div>
            <!-- Runtime map source of truth: local GeoJSON SVG. Do not add bitmap backdrops or duplicate chart labels here. -->
            <div
              class="runtime-map-stage"
              :class="{ dragging: runtimeMapDragging }"
              @pointerdown="startRuntimeMapDrag"
              @pointermove="moveRuntimeMapDrag"
              @pointerup="endRuntimeMapDrag"
              @pointerleave="endRuntimeMapDrag"
              @pointercancel="endRuntimeMapDrag"
              @wheel="handleRuntimeMapWheel"
            >
              <svg class="runtime-region-svg" :viewBox="runtimeSvgViewBox" role="img" aria-label="Greater Bay Area simulation map">
                <!-- Keep every geographic layer in this viewport so pan/zoom moves the whole map, not just the GBA overlay. -->
                <g class="svg-map-viewport" :transform="runtimeSvgMapTransform">
                  <g class="svg-world-backdrop">
                    <path
                      v-for="region in runtimeWorldBackdropRegions"
                      :key="region.name"
                      :d="region.path"
                    />
                  </g>
                  <g class="svg-regions">
                    <path
                      v-for="region in gbaSvgRegions"
                      :key="region.name"
                      :class="{ selected: isRuntimeRegionHighlighted(region.name) }"
                      :d="region.path"
                      :fill="region.color"
                      @pointerenter="setHoveredRuntimeRegion(region.name)"
                      @pointerleave="clearHoveredRuntimeRegion(region.name)"
                      @click.stop="selectRuntimeRegion(region.name)"
                    />
                  </g>
                  <g v-if="selectedRuntimeRegionMarker" class="svg-region-pulse">
                    <circle :cx="selectedRuntimeRegionMarker.x" :cy="selectedRuntimeRegionMarker.y" r="20" />
                    <circle :cx="selectedRuntimeRegionMarker.x" :cy="selectedRuntimeRegionMarker.y" r="6" />
                  </g>
                  <g class="svg-runtime-links">
                    <path
                      v-for="link in runtimeSvgLinks"
                      :key="link.id"
                      :class="['svg-runtime-link', link.type]"
                      :d="link.path"
                      :stroke-width="link.width"
                    />
                  </g>
                  <g class="svg-runtime-enterprises">
                    <g
                      v-for="enterprise in runtimeSvgEnterprises"
                      :key="enterprise.id"
                      class="svg-enterprise-marker"
                      :class="{ selected: enterprise.selected }"
                      :transform="`translate(${enterprise.x} ${enterprise.y})`"
                      @pointerdown.stop
                      @click.stop="openEnterpriseHistory(enterprise.node)"
                    >
                      <circle
                        v-if="enterprise.selected"
                        class="enterprise-selected-ring"
                        :r="enterprise.selectionRadius"
                        :stroke="enterprise.color"
                      />
                      <circle
                        class="svg-enterprise-dot"
                        :class="[enterprise.className, { linked: enterprise.linked, selected: enterprise.selected }]"
                        :r="enterprise.radius"
                        :fill="enterprise.color"
                      />
                    </g>
                  </g>
                  <g class="svg-region-labels">
                    <g
                      v-for="label in gbaSvgLabels"
                      :key="label.name"
                      class="svg-region-label"
                      :class="{ selected: isRuntimeRegionHighlighted(label.name) }"
                      :transform="`translate(${label.x} ${label.y})`"
                      @pointerdown.stop
                      @pointerenter="setHoveredRuntimeRegion(label.name)"
                      @pointerleave="clearHoveredRuntimeRegion(label.name)"
                      @click.stop="selectRuntimeRegion(label.name)"
                    >
                      <g :transform="`scale(${regionLabelScale})`">
                        <text y="5">{{ label.shortName }}</text>
                      </g>
                    </g>
                  </g>
                  <g class="svg-runtime-projects">
                    <g
                      v-for="project in runtimeSvgProjects"
                      :key="project.id"
                      class="svg-project-pin"
                      :class="{ selected: project.selected }"
                      :transform="`translate(${project.x} ${project.y})`"
                      @pointerdown.stop
                      @click.stop="openProjectDetails(project.node)"
                    >
                      <circle v-if="project.selected" class="project-selected-ring" r="22" :stroke="project.color" />
                      <circle class="project-progress-track" r="15.5" />
                      <circle
                        class="project-progress-ring"
                        r="15.5"
                        :stroke="project.color"
                        :stroke-dasharray="project.progressDash"
                        transform="rotate(-90)"
                      />
                      <rect class="project-card" x="-10" y="-11" width="20" height="22" rx="5" />
                      <path class="project-building-outline" d="M-7 8V-5.5C-7 -6.4 -6.4 -7 -5.5 -7H2.5C3.4 -7 4 -6.4 4 -5.5V8M4 -1H6.2C7.2 -1 8 -.2 8 .8V8M-8 8H8" />
                      <path class="project-building-line" d="M-4 -4H1M-4 -.5H1M-4 3H1" />
                      <text class="project-progress" y="27">{{ project.progress }}%</text>
                    </g>
                  </g>
                </g>
              </svg>
              <div ref="runtimeMapRef" class="runtime-geo-map" role="img" aria-label="Greater Bay Area construction simulation map"></div>
              <div class="map-legend-box">
                <div class="legend-section">
                  <h3>Layers</h3>
                  <span><Building2 :size="14" />Projects</span>
                  <span><span class="legend-dot blue"></span>Owner</span>
                  <span><span class="legend-dot teal"></span>Contractor</span>
                  <span><span class="legend-dot purple"></span>Supplier</span>
                  <span><span class="legend-dot rose"></span>Consultant</span>
                  <span><span class="legend-dot slate"></span>Government</span>
                  <span><span class="legend-line orange"></span>Resource flow</span>
                  <span><span class="legend-line purple"></span>Collaboration</span>
                  <span class="legend-status-row"><span class="legend-project construction"></span>Construction</span>
                  <span class="legend-status-row"><span class="legend-project completed"></span>Completed</span>
                  <span class="legend-status-row"><span class="legend-project approval"></span>Approval</span>
                  <span class="legend-status-row"><span class="legend-project tender"></span>Tender / Contract</span>
                </div>
              </div>
              <div class="runtime-map-summary">
                <b>{{ runtimeMapEnterprises.length }}</b>
                <span>visible firms</span>
                <b>{{ runtimeMapLinkCount }}</b>
                <span>runtime links</span>
                <b>{{ mapZoomLabel }}</b>
                <span>map zoom</span>
                <b>{{ gbaCityMeta.length }}</b>
                <span>real regions</span>
              </div>
            </div>
          </section>

          <aside class="panel simulation-side-panel inspector-panel">
            <template v-if="selectedRuntimeProject">
              <div class="inspector-header project">
                <span class="inspector-icon"><Building2 :size="22" /></span>
                <div>
                  <span class="muted">Project Information</span>
                  <h2 :title="selectedRuntimeProject.name">{{ selectedProjectDisplayName }}</h2>
                </div>
                <button class="icon-button" @click="closeRuntimeSelection" aria-label="Close selected item">
                  <ChevronRight :size="17" />
                </button>
              </div>

              <div class="inspector-tags">
                <span>{{ selectedRuntimeProject.city }}</span>
                <span>{{ statusLabel(selectedRuntimeProject.status) }}</span>
                <span>{{ selectedRuntimeProject.stageLabel }}</span>
              </div>

              <section class="inspector-block">
                <div class="inspector-progress-row">
                  <span>Project progress</span>
                  <b>{{ selectedRuntimeProject.progress }}%</b>
                </div>
                <div class="inspector-progress">
                  <i :style="{ width: `${selectedRuntimeProject.progress}%` }"></i>
                </div>
              </section>

              <section class="inspector-grid">
                <span><small>Quality</small><b>{{ Math.round(selectedRuntimeProject.quality || 0) }}%</b></span>
                <span><small>Delay</small><b>{{ selectedRuntimeProject.delayDays || 0 }}d</b></span>
                <span><small>Cost risk</small><b>{{ formatPercent(selectedRuntimeProject.costOverrun || 0) }}</b></span>
                <span><small>Type</small><b>{{ projectTypeLabel(selectedRuntimeProject.projectType) }}</b></span>
              </section>

              <section class="inspector-block">
                <h3><Users :size="16" />Participants</h3>
                <div class="participant-list">
                  <article v-for="participant in selectedProjectParticipants" :key="participant.id">
                    <span :class="['participant-dot', roleClass(participant.role)]"></span>
                    <div>
                      <b>{{ participant.name }}</b>
                      <small>{{ roleDisplayName(participant.role) }} · {{ participant.city }}</small>
                    </div>
                  </article>
                  <p v-if="!selectedProjectParticipants.length">No linked enterprise is active at this playback point.</p>
                </div>
              </section>

              <section class="inspector-block">
                <h3><Clock3 :size="16" />Project milestones</h3>
                <div class="inspector-event-list">
                  <article
                    v-for="event in selectedProjectEvents"
                    :key="event.event_id"
                    :class="{ expanded: isProjectEventExpanded(event.event_id) }"
                  >
                    <button class="event-card-button" @click="toggleProjectEventDetails(event.event_id)">
                      <span class="event-copy">
                        <small>{{ eventTimeLabel(event.tick) }}</small>
                        <b>{{ projectEventTypeLabel(event.event_type) }}</b>
                        <span>{{ friendlyProjectEventDescription(event, selectedRuntimeProject) }}</span>
                      </span>
                      <ChevronDown :size="16" />
                    </button>
                    <div v-if="isProjectEventExpanded(event.event_id)" class="project-event-detail">
                      <div
                        v-for="row in projectEventDetailRows(event, selectedRuntimeProject)"
                        :key="`${event.event_id}-${row.label}`"
                        class="event-detail-row"
                      >
                        <small>{{ row.label }}</small>
                        <b>{{ row.value }}</b>
                      </div>
                      <div v-if="projectEventBidRows(event, selectedRuntimeProject).length" class="event-bid-table">
                        <h4>Bid details</h4>
                        <div v-for="bid in projectEventBidRows(event, selectedRuntimeProject)" :key="bid.id" class="event-bid-row">
                          <span>{{ bid.contractor }}</span>
                          <b>{{ bid.price }}</b>
                          <small>{{ bid.result }}</small>
                        </div>
                      </div>
                    </div>
                  </article>
                  <p v-if="!selectedProjectEvents.length">Project lifecycle milestones will appear as this project advances.</p>
                </div>
              </section>
            </template>

            <template v-else-if="selectedRuntimeEnterprise">
              <div class="inspector-header enterprise">
                <span :class="['inspector-icon', roleClass(selectedRuntimeEnterprise.role)]">
                  <component :is="roleIcon(selectedRuntimeEnterprise.role)" :size="22" />
                </span>
                <div>
                  <span class="muted">Enterprise Agent</span>
                  <h2 :title="selectedEnterpriseName">{{ selectedEnterpriseDisplayName }}</h2>
                </div>
                <button class="icon-button" @click="closeRuntimeSelection" aria-label="Close selected item">
                  <ChevronRight :size="17" />
                </button>
              </div>

              <div class="inspector-tags">
                <span>{{ roleDisplayName(selectedRuntimeEnterprise.role) }}</span>
                <span>{{ selectedRuntimeEnterprise.city }}</span>
                <span>{{ statusLabel(selectedRuntimeEnterprise.status) }}</span>
              </div>

              <div v-if="enterpriseHistoryLoading" class="history-empty compact">Loading behavior history...</div>
              <template v-else>
                <section class="inspector-block enterprise-profile-card">
                  <h3><Building2 :size="16" />Enterprise snapshot</h3>
                  <div class="enterprise-info-grid">
                    <span v-for="item in selectedEnterpriseImportantInfo" :key="item.label">
                      <small>{{ item.label }}</small>
                      <b>{{ item.value }}</b>
                    </span>
                  </div>
                  <div class="enterprise-capability-list">
                    <div v-for="capability in selectedEnterpriseCapabilities" :key="capability.label">
                      <span>{{ capability.label }}</span>
                      <div><i :style="{ width: `${capability.score}%` }"></i></div>
                      <b>{{ capability.value }}</b>
                    </div>
                  </div>
                </section>

                <section class="inspector-block agent-state-card">
                  <h3><BarChart3 :size="16" />Current status</h3>
                  <b>{{ selectedEnterpriseCurrentStatus }}</b>
                  <span>{{ selectedEnterpriseCurrentDescription }}</span>
                </section>

                <section class="inspector-block">
                  <div class="inspector-section-heading">
                    <h3><FileText :size="16" />Recent activity</h3>
                    <button class="activity-toggle-button" @click="enterpriseActivityExpanded = !enterpriseActivityExpanded">
                      {{ enterpriseActivityExpanded ? "Key nodes" : "Full timeline" }}
                    </button>
                  </div>
                  <p class="activity-mode-copy">
                    {{ enterpriseActivityExpanded ? "Every recorded operation for this enterprise, ordered by simulation month." : "Important project milestones and role changes only." }}
                  </p>
                  <div :class="['inspector-event-list', 'enterprise-activity-list', { detailed: enterpriseActivityExpanded }]">
                    <article
                      v-for="event in displayedEnterpriseActivity"
                      :key="event.event_id"
                      :class="{ important: isEnterpriseActivityImportant(event), detailed: enterpriseActivityExpanded }"
                    >
                      <small>{{ eventTimeLabel(event.tick) }}</small>
                      <b>{{ enterpriseActivityTitle(event) }}</b>
                      <span>{{ friendlyEventDescription(event) }}</span>
                      <dl v-if="enterpriseActivityExpanded && enterpriseActivityDetailRows(event).length" class="enterprise-event-details">
                        <template v-for="row in enterpriseActivityDetailRows(event)" :key="`${event.event_id}-${row.label}`">
                          <dt>{{ row.label }}</dt>
                          <dd>{{ row.value }}</dd>
                        </template>
                      </dl>
                    </article>
                    <p v-if="!displayedEnterpriseActivity.length">No recorded behavior event at this playback point.</p>
                  </div>
                </section>
              </template>
            </template>

            <template v-else>
              <div class="inspector-empty">
                <span class="inspector-empty-icon"><MousePointer2 :size="30" /></span>
                <h2>Inspect the simulation</h2>
                <p>Click a project marker or enterprise dot on the map to see progress, participants, behavior history, and current simulation status.</p>
                <div class="inspector-empty-grid">
                  <span><b>{{ liveProjectCount }}</b>Active projects</span>
                  <span><b>{{ runtimeMapEnterprises.length }}</b>Visible firms</span>
                  <span><b>{{ runtimeMapLinkCount }}</b>Runtime links</span>
                </div>
              </div>
            </template>
          </aside>
        </div>
        <div class="metric-cards simulation-kpis">
          <div><Building2 :size="32" /><span>Projects Tracked</span><b>{{ trackedProjectCount }}</b><small>{{ completedProjectCount }} completed · {{ liveProjectCount }} active</small></div>
          <div><Network :size="32" /><span>Runtime Links</span><b>{{ networkEdgeCount }}</b><small>{{ crossCityLinkCount }} cross-city</small></div>
          <div><Users :size="32" /><span>Firms Engaged</span><b>{{ engagedFirms }}</b><small>▲ resource activity</small></div>
          <div><LineChart :size="32" /><span>Resource Flow Index</span><b>{{ resourceFlowIndex }}</b><small>▲ simulation based</small></div>
        </div>
      </section>

      <section
        v-else-if="activeView === 'analytics'"
        :class="['analytics-page simulation-analytics-page', { 'periods-tab-active': analyticsActiveTab === 'periods', 'external-tab-active': analyticsActiveTab === 'external' }]"
      >
        <div class="analytics-tabs">
          <button
            v-for="tab in analyticsTabs"
            :key="tab.key"
            :class="{ active: analyticsActiveTab === tab.key }"
            type="button"
            @click="analyticsActiveTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>

        <template v-if="analyticsActiveTab === 'overview'">
          <div class="analytics-kpi-strip">
            <article
              v-for="card in analyticsOverviewKpis"
              :key="card.key"
              :class="['analytics-kpi-card', card.tone]"
            >
              <span class="analytics-kpi-icon"><component :is="card.icon" :size="27" /></span>
              <div>
                <span>{{ card.label }}</span>
                <b>{{ card.value }}</b>
                <small>{{ card.note }}</small>
              </div>
              <svg class="analytics-sparkline" viewBox="0 0 96 34" aria-hidden="true">
                <polyline :points="sparklinePoints(card.spark)" />
              </svg>
              <button
                v-if="card.formula"
                :class="['analytics-formula-trigger', { open: analyticsFormulaTooltipOpen === card.key }]"
                type="button"
                :aria-label="`${card.label} formula`"
                :title="card.formula"
                @mouseenter="analyticsFormulaTooltipOpen = card.key"
                @mouseleave="analyticsFormulaTooltipOpen = ''"
                @focus="analyticsFormulaTooltipOpen = card.key"
                @blur="analyticsFormulaTooltipOpen = ''"
                @click.stop="analyticsFormulaTooltipOpen = analyticsFormulaTooltipOpen === card.key ? '' : card.key"
              >
                <Info :size="13" />
                <span class="analytics-formula-tooltip" role="tooltip">{{ card.formula }}</span>
              </button>
            </article>
          </div>

          <div class="analytics-primary-grid">
            <section class="panel analytics-performance-panel">
              <div class="analytics-section-heading">
                <div>
                  <h2>Simulation Performance Over Time</h2>
                </div>
                <button class="icon-button analytics-more-button" type="button" aria-label="More options"><MoreVertical :size="18" /></button>
              </div>
              <div class="analytics-control-row">
                <label>
                  <span>Metric Group:</span>
                  <select>
                    <option>Collaboration</option>
                    <option>Resource Flow</option>
                    <option>Risk Exposure</option>
                  </select>
                </label>
                <label>
                  <span>Metric:</span>
                  <select>
                    <option>Collaboration Index</option>
                    <option>Resource Flow Index</option>
                    <option>Regional Balance</option>
                  </select>
                </label>
                <div class="analytics-compare">
                  <span>Compare:</span>
                  <b><i></i>Actual</b>
                  <b><i class="baseline"></i>No-policy Baseline</b>
                </div>
              </div>
              <div class="analytics-chart-legend" aria-hidden="true">
                <b><i></i>Collaboration Index</b>
                <b><i class="baseline"></i>Hop-to-hop Baseline</b>
              </div>
              <div ref="analyticsTrendRef" class="analytics-trend-chart"></div>
            </section>

            <section class="panel analytics-notes-panel">
              <div class="analytics-notes-heading">
                <span class="analytics-notes-title-mark" aria-hidden="true"></span>
                <h2>Key Result Notes</h2>
              </div>
              <article
                v-for="note in analyticsKeyNotes"
                :key="note.title"
                :class="['analytics-note', `tone-${note.tone}`]"
              >
                <span><component :is="note.icon" :size="21" /></span>
                <div>
                  <b>{{ note.title }}</b>
                  <p>{{ note.text }}</p>
                </div>
              </article>
            </section>
          </div>

          <div class="analytics-insight-grid">
            <section class="panel analytics-region-panel">
              <div class="analytics-section-heading compact">
                <div>
                  <h2>Regional Distribution</h2>
                  <p>Collaboration intensity by Greater Bay Area city.</p>
                </div>
                <select>
                  <option>Collaboration Index</option>
                  <option>Project Activity</option>
                </select>
              </div>
              <div class="analytics-region-content">
                <div class="analytics-region-map-wrap">
                  <div class="analytics-heat-legend"><span>Low</span><i></i><b>High</b></div>
                  <div ref="analyticsRegionMapRef" class="analytics-region-map" aria-label="Greater Bay Area regional heatmap"></div>
                </div>
                <aside class="analytics-selected-region">
                  <span>Selected Region</span>
                  <b>{{ selectedAnalyticsRegion.name }}</b>
                  <dl>
                    <dt>Role</dt><dd>{{ selectedAnalyticsRegion.role }}</dd>
                    <dt>Projects</dt><dd>{{ selectedAnalyticsRegion.projects }}</dd>
                    <dt>Firms</dt><dd>{{ selectedAnalyticsRegion.firms }}</dd>
                    <dt>Cross-region Links</dt><dd>{{ selectedAnalyticsRegion.links }}</dd>
                    <dt>Net Resource Flow</dt><dd class="positive">{{ selectedAnalyticsRegion.netFlow }}</dd>
                    <dt>Top Connection</dt><dd>{{ selectedAnalyticsRegion.topConnection }}</dd>
                  </dl>
                  <button type="button">View Details <ArrowRight :size="14" /></button>
                </aside>
              </div>
            </section>

            <section class="panel analytics-resource-panel">
              <div class="analytics-section-heading compact">
                <div>
                  <h2>Resource Flow Overview</h2>
                  <p>Top resource corridors by simulated transfer volume.</p>
                </div>
              </div>
              <div class="analytics-resource-controls">
                <label>
                  <span>View:</span>
                  <select>
                    <option>Top Corridors</option>
                    <option>All Corridors</option>
                  </select>
                </label>
                <label>
                  <span>Resource Type:</span>
                  <select>
                    <option>All</option>
                    <option>Capital</option>
                    <option>Labor</option>
                    <option>Materials</option>
                    <option>Technical</option>
                  </select>
                </label>
              </div>
              <div ref="analyticsResourceFlowRef" class="analytics-resource-flow" aria-label="Resource flow sankey chart"></div>
              <p class="analytics-footnote"><BookOpen :size="14" /> Flow width represents total resource volume.</p>
            </section>

            <section class="panel analytics-collaboration-panel">
              <div class="analytics-section-heading compact">
                <div>
                  <h2>Collaboration Overview</h2>
                  <p>Network density and strongest cross-region corridors.</p>
                </div>
                <select>
                  <option>All Period</option>
                  <option>Policy Period</option>
                </select>
              </div>
              <div class="analytics-collaboration-content">
                <div class="analytics-collab-stats">
                  <div v-for="stat in analyticsCollaborationStats" :key="stat.label">
                    <span>{{ stat.label }}</span>
                    <b>{{ stat.value }}</b>
                    <small>{{ stat.delta }}</small>
                  </div>
                </div>
                <div class="analytics-corridors">
                  <h3>Top Collaboration Corridors</h3>
                  <article v-for="corridor in analyticsCorridors" :key="corridor.label">
                    <span>{{ corridor.rank }}</span>
                    <div>
                      <b>{{ corridor.label }}</b>
                      <i><em :style="{ width: corridor.percent }"></em></i>
                    </div>
                    <strong>{{ corridor.value }}</strong>
                  </article>
                  <button type="button">View Full Network <ArrowRight :size="14" /></button>
                </div>
              </div>
            </section>
          </div>
        </template>

        <template v-else-if="analyticsActiveTab === 'periods'">
          <div class="period-analysis-page">
            <section class="panel period-flow-panel">
              <div class="period-panel-heading">
                <div>
                  <h2>
                    Predefined Periods
                    <button
                      :class="['period-info-trigger', { open: periodInfoOpen }]"
                      type="button"
                      aria-label="Predefined periods explanation"
                      :aria-expanded="periodInfoOpen ? 'true' : 'false'"
                      title="Periods are derived from workflow phase boundaries. Policy and event exposure are counted by overlap. Select a transition card to update the focused comparison below."
                      @click.stop="periodInfoOpen = !periodInfoOpen"
                      @keydown.escape="periodInfoOpen = false"
                      @blur="periodInfoOpen = false"
                    >
                      <Info :size="14" />
                      <span class="period-info-tooltip" role="tooltip">
                        Periods come from Workflow phase boundaries. Policy and event exposure are counted by overlap. Select a transition card to update the focused comparison and Delta Evidence below.
                      </span>
                    </button>
                  </h2>
                </div>
              </div>
              <div class="period-card-flow period-story-flow">
                <template v-for="(period, index) in periodAnalysisPeriods" :key="period.id">
                  <article class="period-summary-card">
                    <span :class="['period-card-accent', period.exposureTone]"></span>
                    <header class="period-card-header">
                      <span class="period-badge">P{{ period.index }}</span>
                      <div>
                        <b>{{ period.shortTitle }}</b>
                        <small>{{ period.range }} · {{ period.duration }} months</small>
                      </div>
                      <span :class="['period-exposure-pill', period.exposureTone]">{{ period.exposure }}</span>
                    </header>
                    <div class="period-stage-summary">
                      <span>Stage</span>
                      <b>{{ period.stage }}</b>
                    </div>
                    <div class="period-card-signals">
                      <span>Policies<b>{{ period.policyCount }}</b></span>
                      <span>Events<b>{{ period.events }}</b></span>
                      <span>Strongest<b>{{ periodDimensionLabel(period, index, "strongest") }}</b></span>
                      <span>Weakest<b>{{ periodDimensionLabel(period, index, "weakest") }}</b></span>
                    </div>
                  </article>
                  <button
                    v-if="periodTransitionSummaries[index]"
                    :class="['period-transition-card', { active: periodFocusedTransitionIndex === index }]"
                    type="button"
                    @click="periodFocusedTransitionIndex = index"
                  >
                    <span class="period-transition-label">{{ periodTransitionSummaries[index].label }}</span>
                    <b>{{ periodTransitionSummaries[index].badge }}</b>
                    <div class="period-transition-metrics">
                      <span
                        v-for="metric in periodTransitionSummaries[index].metrics"
                        :key="metric.label"
                        :class="['period-transition-metric', metric.positive ? 'positive' : 'negative']"
                      >
                        <i><component :is="metric.icon" :size="16" /></i>
                        <span class="period-transition-metric-copy">
                          <small>{{ metric.label }}</small>
                          <strong>{{ metric.value }}</strong>
                        </span>
                        <component :is="metric.positive ? ArrowUp : ArrowDown" :size="14" />
                      </span>
                    </div>
                  </button>
                </template>
              </div>
            </section>

            <div class="period-middle-grid">
              <section class="panel period-matrix-panel">
                <div class="period-matrix-heading">
                  <div>
                    <h2>Period Performance Matrix</h2>
                    <div
                      class="period-score-scale"
                      :aria-label="`Shared score scale from ${periodMatrixScoreDomain.min} low to ${periodMatrixScoreDomain.max} high`"
                    >
                      <span>Low {{ periodMatrixScoreDomain.min }}</span>
                      <i></i>
                      <span>{{ periodMatrixScoreDomain.max }} High</span>
                    </div>
                  </div>
                  <span>Monthly Average</span>
                </div>
                <div class="period-matrix period-matrix-refined" :style="periodMatrixGridStyle">
                  <div class="period-matrix-corner">Metric Group</div>
                  <div v-for="period in periodAnalysisPeriods" :key="`matrix-head-${period.id}`" class="period-matrix-head">
                    <b>P{{ period.index }}</b>
                    <span>{{ period.shortTitle }}</span>
                  </div>
                  <div class="period-matrix-side-head">Best</div>
                  <template v-for="metric in periodAnalysisMatrixRows" :key="metric.key">
                    <div class="period-matrix-label">
                      <span :class="metric.tone"><component :is="metric.icon" :size="16" /></span>
                      <b>{{ metric.label }}</b>
                    </div>
                    <div
                      v-for="cell in metric.cells"
                      :key="`${metric.key}-${cell.period}`"
                      :class="['period-score-cell', 'period-heat-cell', { best: cell.isBest }]"
                      :style="cell.heatStyle"
                    >
                      <strong>{{ cell.score }}</strong>
                    </div>
                    <div :class="['period-matrix-pill', metric.bestTone]">{{ metric.best }}</div>
                  </template>
                </div>
              </section>

              <section class="panel period-ranking-panel">
                <div class="period-ranking-heading">
                  <div>
                    <h2>Transition Impact Ranking</h2>
                    <p>Contribution to total positive movement.</p>
                  </div>
                  <span>{{ periodFocusedTransition.label }}</span>
                </div>
                <div class="period-ranking-summary">
                  <span class="period-ranking-summary-icon"><TrendingUp :size="18" /></span>
                  <div>
                    <small>Composite Average</small>
                    <b>{{ periodDetailedAnalysis.compositeDelta }}</b>
                  </div>
                  <div>
                    <small>Dimensions Improved</small>
                    <b>{{ periodDetailedAnalysis.improvedCount }}</b>
                  </div>
                </div>
                <article v-for="item in periodTransitionRanking" :key="item.key" class="period-driver-row">
                  <span class="period-rank-index">{{ item.rank }}</span>
                  <span :class="['period-rank-icon', item.tone]"><component :is="item.icon" :size="17" /></span>
                  <div class="period-driver-main">
                    <div>
                      <b>{{ item.title }}</b>
                      <strong :class="{ negative: item.negative }">{{ item.value }}</strong>
                    </div>
                    <small>P{{ item.fromPeriod }} {{ item.fromScore }} <ArrowRight :size="10" /> P{{ item.toPeriod }} {{ item.toScore }}</small>
                    <i><em :style="{ width: `${item.contribution}%`, background: item.color }"></em></i>
                  </div>
                  <span class="period-driver-share">{{ item.contribution }}%</span>
                </article>
              </section>
            </div>

            <section class="panel period-transition-workspace-panel">
              <aside class="period-transition-summary-pane">
                <div class="period-result-analysis">
                  <header class="period-result-analysis-head">
                    <div>
                      <span>Selected transition · {{ periodFocusedTransition.label }}</span>
                      <h2>Period Result Analysis</h2>
                      <p>
                        {{ periodFocusedTransition.from.shortTitle }} {{ periodFocusedTransition.from.range }}
                        <ArrowRight :size="13" />
                        {{ periodFocusedTransition.to.shortTitle }} {{ periodFocusedTransition.to.range }}
                      </p>
                    </div>
                    <span :class="['period-analysis-confidence', periodDetailedAnalysis.confidenceTone]">
                      <CheckCircle2 :size="14" />
                      {{ periodDetailedAnalysis.confidence }}
                    </span>
                  </header>

                  <section class="period-executive-assessment">
                    <span class="period-assessment-icon"><TrendingUp :size="22" /></span>
                    <div class="period-assessment-copy">
                      <span>Executive Assessment</span>
                      <b>{{ periodDetailedAnalysis.headline }}</b>
                      <p>{{ periodDetailedAnalysis.summary }}</p>
                    </div>
                    <div class="period-assessment-stats">
                      <div v-for="stat in periodDetailedAnalysis.stats" :key="stat.label">
                        <b>{{ stat.value }}</b>
                        <span>{{ stat.label }}</span>
                      </div>
                    </div>
                  </section>

                  <div class="period-analysis-detail-grid">
                    <section class="period-analysis-block period-priority-findings">
                      <header>
                        <h3>Priority Findings</h3>
                        <span>{{ periodDetailedAnalysis.breadth }}</span>
                      </header>
                      <article v-for="finding in periodDetailedAnalysis.findings" :key="finding.title">
                        <span :class="['period-finding-icon', finding.tone]">
                          <component :is="finding.icon" :size="15" />
                        </span>
                        <div>
                          <b>{{ finding.title }}</b>
                          <p>{{ finding.detail }}</p>
                        </div>
                        <strong :class="{ warning: finding.warning }">{{ finding.value }}</strong>
                      </article>
                    </section>

                    <section class="period-analysis-block period-cross-metric-analysis">
                      <header>
                        <h3>Cross-metric Diagnosis</h3>
                        <span>Impact conversion</span>
                      </header>
                      <div class="period-impact-path">
                        <template v-for="(node, index) in periodDetailedAnalysis.impactPath" :key="node.label">
                          <div :class="node.tone">
                            <span>{{ node.label }}</span>
                            <b>{{ node.value }}</b>
                          </div>
                          <ArrowRight v-if="index < periodDetailedAnalysis.impactPath.length - 1" :size="14" />
                        </template>
                      </div>
                      <div class="period-conversion-readout">
                        <div>
                          <span>Collaboration-to-flow conversion</span>
                          <b>{{ periodDetailedAnalysis.conversionRate }}%</b>
                        </div>
                        <i><em :style="{ width: `${periodDetailedAnalysis.conversionRate}%` }"></em></i>
                        <p>{{ periodDetailedAnalysis.conversionNote }}</p>
                      </div>
                      <div class="period-support-signals">
                        <span v-for="signal in periodDetailedAnalysis.supportSignals" :key="signal.label">
                          <small>{{ signal.label }}</small>
                          <b>{{ signal.value }}</b>
                        </span>
                      </div>
                    </section>
                  </div>

                  <div class="period-analysis-bottom-grid">
                    <section class="period-analysis-block period-evidence-windows">
                      <header>
                        <h3>Evidence Windows</h3>
                        <span>Monthly simulation trace</span>
                      </header>
                      <div class="period-evidence-window-list">
                        <article v-for="evidence in periodDetailedAnalysis.evidenceWindows" :key="evidence.month">
                          <span>{{ evidence.month }}</span>
                          <div>
                            <b>{{ evidence.title }}</b>
                            <p>{{ evidence.detail }}</p>
                          </div>
                        </article>
                      </div>
                    </section>

                    <section class="period-analysis-block period-recommended-actions">
                      <header>
                        <h3>Recommended Actions</h3>
                        <span>For the next period</span>
                      </header>
                      <article v-for="action in periodDetailedAnalysis.actions" :key="action.title">
                        <span><component :is="action.icon" :size="14" /></span>
                        <div>
                          <b>{{ action.title }}</b>
                          <p>{{ action.detail }}</p>
                        </div>
                      </article>
                    </section>
                  </div>
                </div>
              </aside>

              <section class="period-transition-view-pane">
                <div class="period-evidence-head">
                  <div class="period-evidence-title">
                    <h2>
                      Delta Evidence <span>({{ periodFocusedTransition.label }})</span>
                      <Info :size="14" />
                    </h2>
                  </div>
                  <div class="period-evidence-tabs">
                    <button class="active" type="button">Evolution</button>
                    <button type="button">Regional Delta</button>
                    <button type="button">Flow Delta</button>
                    <button type="button">Collaboration Delta</button>
                    <button type="button">Lifecycle Events</button>
                  </div>
                </div>
                <article class="period-evidence-card period-evolution-card">
                  <h3>Metric Evolution by Simulation Month <span>({{ periodDetailedAnalysis.evidenceSource }})</span></h3>
                  <div class="period-evolution-chart-wrap">
                    <div class="period-evolution-legend">
                      <span v-for="metric in periodEvolutionMetrics" :key="metric.key">
                        <i :style="{ background: metric.color }"></i>
                        {{ metric.label }}
                      </span>
                    </div>
                    <svg class="period-evolution-chart" viewBox="0 0 620 240" aria-hidden="true">
                      <g class="period-evolution-bands">
                        <rect
                          v-for="band in periodEvolutionChartBands"
                          :key="band.label"
                          :x="band.x"
                          y="22"
                          :width="band.width"
                          height="164"
                          :class="band.tone"
                        />
                      </g>
                      <g class="period-evolution-grid">
                        <line v-for="tick in periodEvolutionYTicks" :key="`y-${tick.value}`" x1="46" x2="600" :y1="tick.y" :y2="tick.y" />
                        <line
                          v-for="tick in periodEvolutionXTicks"
                          :key="`x-${tick.month}`"
                          :class="tick.boundary ? ['period-evolution-boundary', tick.tone] : 'period-evolution-x-grid'"
                          :x1="tick.x"
                          :x2="tick.x"
                          y1="22"
                          y2="186"
                        />
                      </g>
                      <g class="period-evolution-period-labels">
                        <template v-for="label in periodEvolutionPeriodLabels" :key="label.key">
                          <text :x="label.x" y="48" :class="label.tone">P{{ label.index }}</text>
                          <text :x="label.x" y="64" :class="['period-label-sub', label.tone]">{{ label.title }}</text>
                        </template>
                      </g>
                      <g class="period-evolution-lines">
                        <polyline
                          v-for="series in periodEvolutionSeries"
                          :key="series.key"
                          class="period-evolution-line"
                          :points="series.points"
                          :stroke="series.color"
                        />
                      </g>
                      <g class="period-evolution-axis">
                        <text v-for="tick in periodEvolutionYTicks" :key="`yl-${tick.value}`" x="35" :y="tick.y + 4">{{ tick.value }}</text>
                        <text v-for="tick in periodEvolutionXTicks" :key="`xl-${tick.month}`" :x="tick.x" y="220" :style="{ 'text-anchor': tick.anchor }">{{ tick.label }}</text>
                      </g>
                    </svg>
                  </div>
                </article>
              </section>
            </section>
          </div>
        </template>

        <template v-else>
          <div class="external-change-page">
            <section class="panel external-focus-panel">
              <div class="external-change-title">
                <span><Activity :size="28" /></span>
                <div>
                  <h2>External Change Analysis</h2>
                  <p>Read all external changes together, then switch scope only when a signal needs explanation.</p>
                </div>
              </div>

              <div class="external-mode-tabs" role="tablist" aria-label="External analysis focus">
                <button
                  v-for="mode in externalFocusModes"
                  :key="mode.key"
                  :class="{ active: externalFocusMode === mode.key }"
                  type="button"
                  @click="externalFocusMode = mode.key"
                >
                  <component :is="mode.icon" :size="17" />
                  {{ mode.label }}
                </button>
              </div>

              <div class="external-focus-selector">
                <template v-if="externalFocusMode === 'all'">
                  <div class="external-portfolio-strip">
                    <article v-for="scope in externalPortfolioScopeRows" :key="scope.label" :class="scope.tone">
                      <span><component :is="scope.icon" :size="17" /></span>
                      <div>
                        <b>{{ scope.value }}</b>
                        <small>{{ scope.label }} · {{ scope.note }}</small>
                      </div>
                    </article>
                  </div>
                </template>

                <template v-else-if="externalFocusMode === 'policy'">
                  <button
                    v-for="policy in simulationExternalPolicyRows"
                    :key="policy.id"
                    :class="['external-focus-chip', { active: selectedExternalPolicy?.id === policy.id }]"
                    type="button"
                    @click="selectExternalPolicy(policy.id)"
                  >
                    <Shield :size="17" />
                    <span><b>{{ policy.title }}</b><small>{{ policy.timeLabel }} · {{ policy.periodLabel }}</small></span>
                  </button>
                </template>

                <template v-else-if="externalFocusMode === 'event'">
                  <button
                    v-for="event in simulationExternalEventRows"
                    :key="event.id"
                    :class="['external-focus-chip event', { active: selectedExternalEvent?.id === event.id }]"
                    type="button"
                    @click="selectExternalEvent(event.id)"
                  >
                    <Target :size="17" />
                    <span><b>{{ event.title }}</b><small>{{ event.timeLabel }} · {{ event.periodLabel }}</small></span>
                  </button>
                  <div v-if="!simulationExternalEventRows.length" class="external-empty-focus">
                    <Target :size="18" />
                    <span>No external event is configured in this simulation timeline.</span>
                  </div>
                </template>

                <template v-else-if="externalFocusMode === 'combo'">
                  <div class="external-combo-picker">
                    <div>
                      <span>Policy</span>
                      <button
                        v-for="policy in simulationExternalPolicyRows"
                        :key="policy.id"
                        :class="['external-mini-option', { active: selectedExternalPolicy?.id === policy.id }]"
                        type="button"
                        @click="selectExternalPolicy(policy.id)"
                      >
                        {{ policy.shortTitle }}
                      </button>
                    </div>
                    <div>
                      <span>Event</span>
                      <button
                        v-for="event in simulationExternalEventRows"
                        :key="event.id"
                        :class="['external-mini-option event', { active: selectedExternalEvent?.id === event.id }]"
                        type="button"
                        @click="selectExternalEvent(event.id)"
                      >
                        {{ event.shortTitle }}
                      </button>
                      <em v-if="!simulationExternalEventRows.length">No configured event</em>
                    </div>
                  </div>
                </template>

                <template v-else>
                  <button
                    v-for="window in externalTimeWindowRows"
                    :key="window.id"
                    :class="['external-focus-chip time', { active: selectedExternalWindow?.id === window.id }]"
                    type="button"
                    @click="selectedExternalWindowId = window.id"
                  >
                    <Timer :size="17" />
                    <span><b>{{ window.title }}</b><small>{{ window.range }} · {{ window.basis }}</small></span>
                  </button>
                </template>
              </div>
            </section>

            <section class="panel external-unified-analysis-panel">
              <div class="analytics-section-heading compact">
                <div>
                  <h2>Overall External Change Analysis</h2>
                  <p>Conclusion, impact signals, risk reading, and experiment basis in one view.</p>
                </div>
                <span :class="['external-change-status', externalOverallAssessment.tone]">{{ externalOverallAssessment.badge }}</span>
              </div>
              <div class="external-unified-analysis-layout">
                <article class="external-overall-verdict">
                  <span :class="externalOverallAssessment.tone"><component :is="externalOverallAssessment.icon" :size="23" /></span>
                  <div>
                    <small>Overall Conclusion</small>
                    <b>{{ externalOverallAssessment.title }}</b>
                    <p>{{ externalOverallAssessment.text }}</p>
                  </div>
                </article>

                <div class="external-unified-impact">
                  <div class="external-change-profile">
                    <article v-for="item in externalFocusProfileStats" :key="item.label">
                      <span>{{ item.label }}</span>
                      <b>{{ item.value }}</b>
                    </article>
                  </div>
                  <div class="external-impact-bars">
                    <article v-for="metric in externalFocusMetricRows" :key="metric.key">
                      <div>
                        <span><component :is="metric.icon" :size="17" />{{ metric.label }}</span>
                        <b :class="{ negative: metric.negative }">{{ metric.deltaLabel }}</b>
                      </div>
                      <i><em :style="{ width: metric.width, background: metric.color }"></em></i>
                      <small>{{ metric.detail }}</small>
                    </article>
                  </div>
                </div>

                <div class="external-overall-fields compact">
                  <article v-for="row in externalOverallFormRows" :key="row.label">
                    <span>{{ row.label }}</span>
                    <b :class="{ negative: row.negative }">{{ row.value }}</b>
                    <small>{{ row.note }}</small>
                  </article>
                </div>
              </div>
            </section>

            <div class="external-analysis-grid">
              <section class="panel external-risk-panel">
                <div class="analytics-section-heading compact">
                  <div>
                    <h2>Risk Analysis</h2>
                    <p>Potential risks and the conditions that make them appear.</p>
                  </div>
                </div>
                <div class="external-risk-score">
                  <span :class="externalRiskSummary.tone"><AlertTriangle :size="27" /></span>
                  <div>
                    <b>{{ externalRiskSummary.probability }}</b>
                    <small>{{ externalRiskSummary.label }}</small>
                  </div>
                </div>
                <div class="external-risk-matrix">
                  <article v-for="risk in externalRiskMatrixRows" :key="risk.title">
                    <span :class="risk.tone">{{ risk.level }}</span>
                    <div>
                      <b>{{ risk.title }}</b>
                      <small>{{ risk.evidence }}</small>
                    </div>
                    <strong>{{ risk.probability }}</strong>
                  </article>
                </div>
              </section>

              <section class="panel external-trigger-panel">
                <div class="analytics-section-heading compact">
                  <div>
                    <h2>Risk Trigger Conditions</h2>
                    <p>Watch these thresholds across repeated runs.</p>
                  </div>
                </div>
                <div class="external-trigger-list">
                  <article v-for="trigger in externalRiskTriggerRows" :key="trigger.label">
                    <span :class="trigger.tone"><component :is="trigger.icon" :size="17" /></span>
                    <div>
                      <b>{{ trigger.label }}</b>
                      <small>{{ trigger.condition }}</small>
                    </div>
                    <strong>{{ trigger.threshold }}</strong>
                  </article>
                </div>
              </section>
            </div>

            <div class="external-evidence-grid">
              <section class="panel external-run-panel">
                <div class="analytics-section-heading compact">
                  <div>
                    <h2>Multi-run Comparison</h2>
                    <p>External changes are judged by distribution across repeated runs, not one outcome.</p>
                  </div>
                </div>
                <div class="external-run-distribution">
                  <article v-for="row in externalRunDistributionRows" :key="row.label">
                    <span>{{ row.label }}</span>
                    <i>
                      <em class="range" :style="{ left: row.rangeStart, width: row.rangeWidth }"></em>
                      <em class="mean" :style="{ left: row.meanPosition }"></em>
                    </i>
                    <b :class="{ negative: row.negative }">{{ row.value }}</b>
                  </article>
                </div>
              </section>

              <section class="panel external-lifecycle-panel">
                <div class="analytics-section-heading compact">
                  <div>
                    <h2>Lifecycle Evidence</h2>
                    <p>Where the selected external change enters the project lifecycle.</p>
                  </div>
                </div>
                <div class="external-lifecycle-list">
                  <article v-for="stage in externalLifecycleRows" :key="stage.label">
                    <span :class="stage.tone"><component :is="stage.icon" :size="18" /></span>
                    <div>
                      <b>{{ stage.label }}</b>
                      <small>{{ stage.evidence }}</small>
                    </div>
                    <strong :class="{ negative: stage.negative }">{{ stage.delta }}</strong>
                  </article>
                </div>
              </section>

              <section class="panel external-period-panel">
                <div class="analytics-section-heading compact">
                  <div>
                    <h2>Period Impact</h2>
                    <p>Exposure and effect by predefined period or selected time window.</p>
                  </div>
                </div>
                <div class="external-period-list">
                  <article v-for="period in externalFocusPeriodRows" :key="period.id">
                    <span>{{ period.label }}</span>
                    <div>
                      <b>{{ period.title }}</b>
                      <small>{{ period.range }}</small>
                    </div>
                    <i><em :style="{ width: period.width }"></em></i>
                    <strong :class="{ negative: period.negative }">{{ period.delta }}</strong>
                  </article>
                </div>
              </section>

              <section class="panel external-region-panel">
                <div class="analytics-section-heading compact">
                  <div>
                    <h2>Region & Role Breakdown</h2>
                    <p>Most sensitive cities and enterprise roles.</p>
                  </div>
                </div>
                <div class="external-region-list">
                  <article v-for="row in externalRegionRoleRows" :key="row.label">
                    <span>{{ row.rank }}</span>
                    <div>
                      <b>{{ row.label }}</b>
                      <small>{{ row.reason }}</small>
                    </div>
                    <i><em :style="{ width: row.width, background: row.color }"></em></i>
                    <strong>{{ row.value }}</strong>
                  </article>
                </div>
              </section>
            </div>

            <section class="panel external-conclusion-panel">
              <div class="analytics-section-heading compact">
                <div>
                  <h2>Analysis Summary</h2>
                  <p>Interprets effect, robustness, and risk conditions for the active external-change scope.</p>
                </div>
              </div>
              <article v-for="note in externalAnalysisSummary.notes" :key="note.title" class="external-summary-note">
                <span :class="note.tone"><component :is="note.icon" :size="18" /></span>
                <div>
                  <b>{{ note.title }}</b>
                  <p>{{ note.text }}</p>
                </div>
              </article>
            </section>
          </div>
        </template>
      </section>

      <section v-else class="panel placeholder-page">
        <div class="placeholder-hero">
          <span class="round-icon large orange"><component :is="placeholderIcon" :size="28" /></span>
          <div>
            <h2>{{ pageTitle }}</h2>
            <p>{{ pageSubtitle || "A compact workspace for configuring and reviewing the simulation platform." }}</p>
          </div>
        </div>
        <div class="module-card-grid">
          <div v-for="card in placeholderCards" :key="card.title">
            <component :is="card.icon" :size="24" />
            <b>{{ card.title }}</b>
            <span>{{ card.text }}</span>
          </div>
        </div>
        <div class="module-summary">
          <div><b>{{ displayAgentTotal }}</b><span>Enterprise Agents</span></div>
          <div><b>{{ policyRows.length }}</b><span>Policy Scenarios</span></div>
          <div><b>{{ activeProjectsCount }}</b><span>Active Projects</span></div>
          <div><b>{{ crossRegionShare }}%</b><span>Cross-region Links</span></div>
        </div>
      </section>

    </main>

    <Teleport to="body">
      <Transition name="causal-modal">
        <div
          v-if="policyCausalModalOpen && selectedPolicyModule && selectedPolicyInterventionNode"
          class="causal-modal-backdrop"
          @click.self="closePolicyCausalModal"
          @keydown.esc.stop="closePolicyCausalModal"
        >
          <section
            ref="policyCausalModal"
            :class="['causal-chain-modal', selectedPolicyModule.tone]"
            role="dialog"
            aria-modal="true"
            aria-labelledby="selected-causal-chain-title"
            tabindex="-1"
          >
            <header class="causal-modal-header">
              <div class="causal-chain-title">
                <small>Atomic rule · {{ selectedPolicyModule.label }}</small>
                <h2 id="selected-causal-chain-title">{{ selectedPolicyInterventionNode.instrument }}</h2>
                <p>{{ selectedPolicyRuleNarrative }}</p>
              </div>
              <button
                type="button"
                class="causal-modal-close"
                aria-label="Close causal chain"
                @click="closePolicyCausalModal"
              >
                <X :size="18" />
              </button>
            </header>

            <div class="causal-modal-body">
              <div class="causal-chain-flow">
                <template v-for="(step, index) in selectedPolicyCausalChain" :key="step.id">
                  <article :class="['causal-chain-step', step.tone]">
                    <div>
                      <span>{{ String(index + 1).padStart(2, "0") }}</span>
                      <em>{{ step.status }}</em>
                    </div>
                    <small>{{ step.label }}</small>
                    <b>{{ step.value }}</b>
                    <p>{{ step.detail }}</p>
                  </article>
                  <ArrowRight v-if="index < selectedPolicyCausalChain.length - 1" :size="16" class="causal-chain-arrow" />
                </template>
              </div>

              <div class="causal-configuration">
                <div class="causal-assumption-control">
                  <div class="causal-control-heading">
                    <div>
                      <small>Parent package intensity</small>
                      <b>{{ policyUi(selectedPolicyInterventionNode.item.name) }}</b>
                    </div>
                    <button
                      type="button"
                      :class="['causal-include-button', { active: selectedPolicyInterventionNode.selected }]"
                      @click="toggleAtomicInstrument(selectedPolicyInterventionNode.id)"
                    >
                      <CheckCircle2 v-if="selectedPolicyInterventionNode.selected" :size="14" />
                      <Plus v-else :size="14" />
                      {{ selectedPolicyInterventionNode.selected ? "Included" : "Include" }}
                    </button>
                  </div>
                  <p>{{ policyUi(selectedPolicyInterventionNode.item.description) }}</p>
                  <div class="causal-control-bottom">
                    <div class="instrument-strength-row" role="group" aria-label="Instrument implementation intensity">
                      <button
                        v-for="strength in mechanismStrengthOptions"
                        :key="`causal-${selectedPolicyInterventionNode.packageId}-${strength.key}`"
                        :class="{
                          active:
                            !selectedPolicyRuleIsCustom &&
                            mechanismStrengthDraft[selectedPolicyInterventionNode.packageId] === strength.key
                        }"
                        type="button"
                        @click="setSelectedPolicyRulePreset(selectedPolicyInterventionNode.packageId, strength.key)"
                      >
                        {{ policyUi(strength.label) }}
                      </button>
                      <button
                        type="button"
                        :class="{ active: selectedPolicyRuleIsCustom }"
                        @click="enableSelectedPolicyRuleCustomValue"
                      >
                        Custom
                      </button>
                    </div>
                    <span>{{ selectedPolicyIntensitySummary }}</span>
                  </div>
                  <div v-if="selectedPolicyRuleIsCustom" class="causal-custom-value-editor">
                    <div>
                      <small>Custom target value</small>
                      <label>
                        <span>{{ selectedPolicyInterventionNode.rule.before }}</span>
                        <ArrowRight :size="13" aria-hidden="true" />
                        <input
                          ref="policyCustomRuleInput"
                          :type="selectedPolicyCustomInputConfig.type"
                          :min="selectedPolicyCustomInputConfig.min"
                          :max="selectedPolicyCustomInputConfig.max"
                          :step="selectedPolicyCustomInputConfig.step"
                          :inputmode="selectedPolicyCustomInputConfig.inputmode"
                          :value="selectedPolicyInterventionNode.rule.after"
                          :aria-label="`Custom target value for ${selectedPolicyInterventionNode.instrument}`"
                          @input="updateSelectedPolicyRuleCustomValue($event.target.value)"
                          @blur="commitSelectedPolicyRuleCustomValue"
                          @keydown.enter="$event.target.blur()"
                        />
                        <em v-if="selectedPolicyInterventionNode.rule.unit">
                          {{ policyUi(selectedPolicyInterventionNode.rule.unit) }}
                        </em>
                      </label>
                    </div>
                    <p>
                      Applies only to {{ selectedPolicyInterventionNode.instrument }}; other rules keep the
                      {{ policyUi(getMechanismStrengthLabel(mechanismStrengthDraft[selectedPolicyInterventionNode.packageId])) }}
                      package preset.
                    </p>
                  </div>
                </div>

                <div class="causal-rule-preview">
                  <div class="causal-rule-heading">
                    <small>Selected atomic rule</small>
                    <b>{{ selectedPolicyInterventionNode.rule.id }}</b>
                  </div>
                  <dl class="causal-rule-fields">
                    <div class="causal-rule-field variable">
                      <dt>Mapped variable</dt>
                      <dd>{{ policyUi(selectedPolicyInterventionNode.rule.name) }}</dd>
                    </div>
                    <div class="causal-rule-field change">
                      <dt>Value change</dt>
                      <dd>
                        <span>{{ selectedPolicyInterventionNode.rule.before }}</span>
                        <ArrowRight :size="13" aria-hidden="true" />
                        <strong>
                          {{ selectedPolicyInterventionNode.rule.after
                          }}{{ selectedPolicyInterventionNode.rule.unit ? ` ${policyUi(selectedPolicyInterventionNode.rule.unit)}` : "" }}
                        </strong>
                      </dd>
                    </div>
                    <div class="causal-rule-field evidence">
                      <dt>Evidence</dt>
                      <dd>
                        <span>
                          {{ selectedPolicyInterventionNode.rule.customized
                          ? "Custom override"
                          : policyUi(selectedPolicyInterventionNode.rule.source) }}
                        </span>
                        <small>
                          {{ selectedPolicyInterventionNode.rule.customized
                          ? "Pending review"
                          : `Confidence ${selectedPolicyInterventionNode.rule.confidence}` }}
                        </small>
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            </div>
          </section>
        </div>
      </Transition>
    </Teleport>

    <div v-if="agentModalOpen" class="modal-backdrop" @click.self="closeAgentModal">
      <section class="agent-create-modal" role="dialog" aria-modal="true">
        <header class="modal-header">
          <span :class="['modal-mark', agentModalMode === 'ai' ? 'ai' : 'create']">
            <component :is="agentModalMode === 'ai' ? Sparkles : FilePlus2" :size="24" />
          </span>
          <div>
            <h2>{{ agentModalMode === "ai" ? "AI Generate Agent" : "Create Agent" }}</h2>
            <p>
              {{ agentModalMode === "ai"
                ? "Describe the enterprise you need. The generated agent will be marked as Virtual/Synthetic."
                : "Upload real enterprise data or manually configure a simulation-ready agent profile." }}
            </p>
          </div>
          <button class="modal-close" @click="closeAgentModal" aria-label="Close agent modal">×</button>
        </header>

        <template v-if="agentModalMode === 'create'">
          <div class="modal-mode-tabs">
            <button :class="{ active: agentCreateSourceMode === 'manual' }" @click="agentCreateSourceMode = 'manual'">
              <FileText :size="17" />Manual Fields
            </button>
            <button :class="{ active: agentCreateSourceMode === 'upload' }" @click="agentCreateSourceMode = 'upload'">
              <FolderOpen :size="17" />Upload Data
            </button>
          </div>

          <div class="modal-grid">
            <div class="modal-form-stack">
              <div v-if="agentCreateSourceMode === 'upload'" class="upload-panel">
                <label class="upload-tile">
                  <input type="file" multiple accept=".csv,.xlsx,.xls,.json,.parquet" @change="handleAgentFiles" />
                  <FolderOpen :size="24" />
                  <b>Upload files</b>
                  <span>CSV, Excel, JSON, Parquet</span>
                </label>
                <label class="upload-tile">
                  <input type="file" multiple webkitdirectory directory @change="handleAgentFiles" />
                  <Database :size="24" />
                  <b>Upload folder</b>
                  <span>Batch source folder with raw enterprise data</span>
                </label>
                <div class="upload-summary">
                  <strong>{{ uploadedAgentFiles.length || 0 }} files selected</strong>
                  <span>{{ uploadedAgentFiles.length ? uploadedAgentFiles.slice(0, 3).join(", ") : "No source files selected yet." }}</span>
                </div>
              </div>

              <h3 class="form-section-title">Identity, Source & Scale</h3>
              <div class="form-grid two">
                <label>
                  <span>Enterprise Name</span>
                  <input v-model="agentForm.name" placeholder="e.g. Shenzhen Infrastructure Contractor" />
                </label>
                <label>
                  <span>Role</span>
                  <select v-model="agentForm.role">
                    <option>Owner</option>
                    <option>Contractor</option>
                    <option>Architect</option>
                    <option>QS</option>
                    <option>Supplier</option>
                    <option>Consultant</option>
                    <option>Government</option>
                  </select>
                </label>
                <label>
                  <span>Region</span>
                  <select v-model="agentForm.region">
                    <option>Shenzhen</option>
                    <option>Guangzhou</option>
                    <option>Hong Kong</option>
                    <option>Macau</option>
                    <option>Zhuhai</option>
                    <option>Foshan</option>
                    <option>Dongguan</option>
                  </select>
                </label>
                <label>
                  <span>Data Source Type</span>
                  <select v-model="agentForm.sourceCategory">
                    <option value="real_user">Real user upload</option>
                    <option value="real_public">Real public registry</option>
                    <option value="synthetic">Synthetic draft</option>
                  </select>
                </label>
                <label>
                  <span>Employees</span>
                  <input v-model.number="agentForm.employees" type="number" min="0" />
                </label>
                <label>
                  <span>Annual Revenue (B CNY)</span>
                  <input v-model.number="agentForm.annualRevenue" type="number" min="0" step="0.1" />
                </label>
                <label>
                  <span>Enterprise Type</span>
                  <select v-model="agentForm.enterpriseType">
                    <option>Owner</option>
                    <option>Main Contractor</option>
                    <option>Architect</option>
                    <option>QS Consultant</option>
                    <option>Supplier</option>
                    <option>Government Agency</option>
                  </select>
                </label>
                <label>
                  <span>Scale</span>
                  <select v-model="agentForm.scale">
                    <option>Small Scale</option>
                    <option>Medium Scale</option>
                    <option>Large Scale</option>
                    <option>Regional Group</option>
                  </select>
                </label>
                <label>
                  <span>Ownership</span>
                  <select v-model="agentForm.ownership">
                    <option>Private</option>
                    <option>State-owned</option>
                    <option>Public Agency</option>
                    <option>Joint Venture</option>
                    <option>Listed Company</option>
                  </select>
                </label>
                <label>
                  <span>Service Scope</span>
                  <input v-model="agentForm.serviceScope" placeholder="GBA, National, Cross-border..." />
                </label>
              </div>

              <label class="wide-field">
                <span>Capability / Scope Notes</span>
                <textarea v-model="agentForm.description" rows="3" placeholder="Core project types, policy response, cross-region experience, data assumptions..." />
              </label>

              <h3 class="form-section-title">Resource, Collaboration & Capabilities</h3>
              <div class="form-grid two compact">
                <label>
                  <span>Active Regions</span>
                  <input v-model="agentForm.activeRegions" placeholder="Shenzhen, Hong Kong..." />
                </label>
                <label>
                  <span>Preferred Partners</span>
                  <input v-model="agentForm.preferredPartners" placeholder="Local contractor, green supplier..." />
                </label>
              </div>

              <div class="capability-section-grid">
                <section v-for="section in capabilitySections" :key="section.title" class="capability-section">
                  <h3>{{ section.title }}</h3>
                  <label v-for="item in section.items" :key="item.key">
                    <span>{{ item.label }} <b>{{ Number(agentForm[item.key]).toFixed(2) }}</b></span>
                    <input v-model.number="agentForm[item.key]" type="range" min="0" max="1" step="0.01" />
                  </label>
                </section>
              </div>
            </div>

            <aside class="modal-guidance">
              <h3>Simulation Data Requirements</h3>
              <p>Imported records should preserve source boundaries and remain traceable before they enter the simulation engine.</p>
              <ul>
                <li>Keep <b>real_user</b>, <b>real_public</b>, and <b>synthetic</b> separated.</li>
                <li>Record source file, sheet, row, or folder metadata where available.</li>
                <li>Hong Kong and Macau records should keep separate region and qualification logic.</li>
                <li>Generated or incomplete fields should be marked as assumptions, not sourced facts.</li>
                <li>Validation should check unique IDs, non-empty names, GBA city scope, and source IDs.</li>
              </ul>
              <div class="validation-card">
                <Shield :size="20" />
                <div>
                  <b>Validation-ready</b>
                  <span>New agents include source category, capability assumptions, and simulation tags.</span>
                </div>
              </div>
            </aside>
          </div>
        </template>

        <template v-else>
          <div class="ai-modal-grid">
            <div class="modal-form-stack">
              <label class="wide-field">
                <span>Describe the agent you need</span>
                <textarea v-model="aiAgentForm.prompt" rows="6" placeholder="Example: Generate a Shenzhen contractor with strong EPC delivery, high safety management, green construction capability, and cross-border collaboration experience." />
              </label>
              <div class="form-grid two">
                <label>
                  <span>Target Role</span>
                  <select v-model="aiAgentForm.role">
                    <option>Contractor</option>
                    <option>Owner</option>
                    <option>Architect</option>
                    <option>QS</option>
                    <option>Supplier</option>
                    <option>Consultant</option>
                  </select>
                </label>
                <label>
                  <span>Target Region</span>
                  <select v-model="aiAgentForm.region">
                    <option>Shenzhen</option>
                    <option>Guangzhou</option>
                    <option>Hong Kong</option>
                    <option>Macau</option>
                    <option>Zhuhai</option>
                    <option>Foshan</option>
                  </select>
                </label>
                <label>
                  <span>Project Focus</span>
                  <select v-model="aiAgentForm.projectFocus">
                    <option>Infrastructure</option>
                    <option>Commercial Buildings</option>
                    <option>Green Construction</option>
                    <option>Industrial Facilities</option>
                    <option>Public Works</option>
                  </select>
                </label>
                <label>
                  <span>Collaboration Profile</span>
                  <select v-model="aiAgentForm.collaborationProfile">
                    <option>Cross-region coordinator</option>
                    <option>Local delivery specialist</option>
                    <option>Low-carbon policy adapter</option>
                    <option>Cost and claim control</option>
                    <option>Supply-chain resilience</option>
                  </select>
                </label>
              </div>
              <div class="ai-constraint-row">
                <span><Shield :size="17" />Mark as Virtual/Synthetic</span>
                <span><Database :size="17" />Register assumptions</span>
                <span><Network :size="17" />Simulation-ready capabilities</span>
              </div>
            </div>
            <aside class="modal-guidance ai">
              <h3>AI Generation Rules</h3>
              <p>AI generated agents are useful for scenarios, but they must not masquerade as real companies.</p>
              <ul>
                <li>Output is tagged as <b>Virtual</b> and <b>synthetic</b>.</li>
                <li>Names and notes clearly indicate generated simulation data.</li>
                <li>Capabilities are derived from user requirements and documented as assumptions.</li>
              </ul>
            </aside>
          </div>
        </template>

        <footer class="modal-footer">
          <button class="ghost-button" @click="closeAgentModal">Cancel</button>
          <button class="primary-button" @click="submitAgentModal" :disabled="agentLoading">
            <component :is="agentModalMode === 'ai' ? Sparkles : Plus" :size="17" />
            {{ agentModalMode === "ai" ? "Generate Agent" : "Create Agent" }}
          </button>
        </footer>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import * as echarts from "echarts";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BarChart3,
  BookOpen,
  Bot,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock3,
  Copy,
  Database,
  DraftingCompass,
  FileCog,
  FilePlus2,
  FileText,
  FolderDown,
  FolderOpen,
  Filter,
  Globe2,
  GitMerge,
  Handshake,
  HardHat,
  Home,
  Info,
  LineChart,
  Layers3,
  MapPin,
  MousePointer2,
  MoreVertical,
  Network,
  Package,
  Pause,
  PieChart,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Scissors,
  Send,
  Settings,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Star,
  Target,
  Timer,
  TrendingUp,
  Trash2,
  UserRound,
  Users,
  Workflow,
  X,
  Zap,
  ZoomIn,
  ZoomOut
} from "lucide-vue-next";
import { api } from "./api";
import { agentApi } from "./api/agentApi";
import { analyticsApi } from "./api/analyticsApi";
import { clusterApi } from "./api/clusterApi";
import { policyApi } from "./api/policyApi";
import { simulationApi } from "./api/simulationApi";
import { workflowApi } from "./api/workflowApi";
import ProcurementSelector from "./components/ProcurementSelector.vue";
import ProcurementReceipt from "./components/ProcurementReceipt.vue";
import { analyticsNetworkToGraph, analyticsTrendToHistory } from "./adapters/analyticsAdapter";
import { toAgentProfileUi, toAgentRow } from "./adapters/agentAdapter";
import { toClusterComposition, toClusterRow } from "./adapters/clusterAdapter";
import { toPolicyImpacts, toPolicyParams, toPolicyRow } from "./adapters/policyAdapter";
import { runtimeToLegacyResult } from "./adapters/simulationAdapter";
import chinaGeoJson from "./data/chinaGeojson.json";
import gbaGeoJson from "./data/gbaGeojson.json";
import worldGeoJson from "./data/worldGeojson.json";
import { gbaCityMeta, gbaCityNameByRegion } from "./data/gbaMapMeta";

const WORLD_GBA_MAP_NAME = "world-gba-simulation-map";
const GBA_ANALYTICS_MAP_NAME = "gba-analytics-heatmap";
const worldFeaturesWithoutChina = (worldGeoJson.features || []).filter((feature) => feature.properties?.name !== "China");
const worldGbaGeoJson = {
  type: "FeatureCollection",
  features: [
    ...worldFeaturesWithoutChina,
    ...(chinaGeoJson.features || []),
    ...(gbaGeoJson.features || [])
  ]
};
const runtimeWorldBackdropGeoJson = {
  type: "FeatureCollection",
  features: [
    ...worldFeaturesWithoutChina,
    ...(chinaGeoJson.features || [])
  ]
};
const gbaRegionNameSet = new Set(gbaCityMeta.map((city) => city.name));
const runtimeSvgViewBox = "0 0 1000 600";
const gbaSvgProjection = buildGbaSvgProjection(gbaGeoJson, 1000, 600, 58);
const gbaSvgRegions = buildGbaSvgRegions(gbaGeoJson, gbaSvgProjection);
const runtimeWorldBackdropRegions = buildBackdropSvgRegions(runtimeWorldBackdropGeoJson, gbaSvgProjection);
const gbaFeatureIndex = buildGbaFeatureIndex(gbaGeoJson);
const spatialPointCache = new Map();
const gbaSvgLabels = gbaCityMeta.map((city) => {
  const [longitude, latitude] = cityLabelLngLat(city.name);
  const [x, y] = projectSvgPoint(longitude, latitude);
  const shortName = city.name.replace(" SAR", "");
  const width = Math.max(55, shortName.length * 9 + 24);
  return {
    name: city.name,
    shortName,
    x,
    y,
    width,
    rectX: Number((-width / 2).toFixed(1))
  };
});

echarts.registerMap(WORLD_GBA_MAP_NAME, worldGbaGeoJson);
echarts.registerMap(GBA_ANALYTICS_MAP_NAME, gbaGeoJson);

function collectLngLatPairs(node, result = []) {
  if (!Array.isArray(node)) return result;
  if (typeof node[0] === "number" && typeof node[1] === "number") {
    result.push(node);
    return result;
  }
  node.forEach((child) => collectLngLatPairs(child, result));
  return result;
}

function buildGbaSvgProjection(geoJson, width, height, padding) {
  const points = collectLngLatPairs((geoJson.features || []).map((feature) => feature.geometry?.coordinates));
  const lngValues = points.map((point) => point[0]);
  const latValues = points.map((point) => point[1]);
  const minLng = Math.min(...lngValues);
  const maxLng = Math.max(...lngValues);
  const minLat = Math.min(...latValues);
  const maxLat = Math.max(...latValues);
  const scale = Math.min((width - padding * 2) / Math.max(maxLng - minLng, 1), (height - padding * 2) / Math.max(maxLat - minLat, 1));
  const projectedWidth = (maxLng - minLng) * scale;
  const projectedHeight = (maxLat - minLat) * scale;
  return {
    width,
    height,
    padding,
    minLng,
    maxLat,
    scale,
    offsetX: (width - projectedWidth) / 2,
    offsetY: (height - projectedHeight) / 2
  };
}

function projectPointWithProjection(projection, longitude, latitude) {
  const x = projection.offsetX + (Number(longitude) - projection.minLng) * projection.scale;
  const y = projection.offsetY + (projection.maxLat - Number(latitude)) * projection.scale;
  return [Number(x.toFixed(1)), Number(y.toFixed(1))];
}

function projectSvgPoint(longitude, latitude) {
  return projectPointWithProjection(gbaSvgProjection, longitude, latitude);
}

function ringToSvgPath(ring, projection = gbaSvgProjection) {
  return ring
    .map(([longitude, latitude], index) => {
      const [x, y] = projectPointWithProjection(projection, longitude, latitude);
      return `${index === 0 ? "M" : "L"}${x} ${y}`;
    })
    .join(" ");
}

function featureToSvgPath(feature, projection = gbaSvgProjection) {
  const geometry = feature.geometry || {};
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates || [];
  return polygons
    .flatMap((polygon) => polygon.map((ring) => `${ringToSvgPath(ring, projection)} Z`))
    .join(" ");
}

function buildGbaSvgRegions(geoJson, projection = gbaSvgProjection) {
  return (geoJson.features || []).map((feature) => {
    const name = feature.properties?.name || "";
    return {
      name,
      path: featureToSvgPath(feature, projection),
      color: cityMetaFor(name).color
    };
  });
}

function buildBackdropSvgRegions(geoJson, projection) {
  return (geoJson.features || []).map((feature, index) => ({
    name: feature.properties?.name || `background-${index}`,
    path: featureToSvgPath(feature, projection)
  }));
}

function cityLabelLngLat(cityName) {
  const normalizedCity = normalizeCityName(cityName);
  const feature = gbaFeatureIndex.byName.get(normalizedCity);
  const fallback = cityMetaFor(normalizedCity).center;
  if (!feature) return fallback;
  const centroid = featureLargestRingCentroid(feature);
  if (centroid && featureContainsLngLat(feature, centroid[0], centroid[1])) return centroid;
  const bounds = gbaFeatureIndex.bounds.get(normalizedCity);
  if (bounds) {
    const center = [
      Number(((bounds.minLng + bounds.maxLng) / 2).toFixed(6)),
      Number(((bounds.minLat + bounds.maxLat) / 2).toFixed(6))
    ];
    if (featureContainsLngLat(feature, center[0], center[1])) return center;
  }
  return fallback;
}

function featureLargestRingCentroid(feature) {
  const geometry = feature?.geometry || {};
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates || [];
  let largestRing = null;
  let largestArea = 0;
  polygons.forEach((polygon) => {
    const ring = polygon?.[0] || [];
    const area = Math.abs(ringSignedArea(ring));
    if (area > largestArea) {
      largestArea = area;
      largestRing = ring;
    }
  });
  return ringCentroid(largestRing);
}

function ringSignedArea(ring) {
  if (!Array.isArray(ring) || ring.length < 3) return 0;
  let area = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const [x1, y1] = ring[index];
    const [x2, y2] = ring[(index + 1) % ring.length];
    area += x1 * y2 - x2 * y1;
  }
  return area / 2;
}

function ringCentroid(ring) {
  if (!Array.isArray(ring) || ring.length < 3) return null;
  let twiceArea = 0;
  let cx = 0;
  let cy = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const [x1, y1] = ring[index];
    const [x2, y2] = ring[(index + 1) % ring.length];
    const cross = x1 * y2 - x2 * y1;
    twiceArea += cross;
    cx += (x1 + x2) * cross;
    cy += (y1 + y2) * cross;
  }
  if (Math.abs(twiceArea) < 1e-9) return null;
  return [
    Number((cx / (3 * twiceArea)).toFixed(6)),
    Number((cy / (3 * twiceArea)).toFixed(6))
  ];
}

function buildGbaFeatureIndex(geoJson) {
  const byName = new Map();
  const bounds = new Map();
  (geoJson.features || []).forEach((feature) => {
    const name = normalizeCityName(feature.properties?.name || "");
    if (!name) return;
    byName.set(name, feature);
    bounds.set(name, featureBounds(feature));
  });
  return { byName, bounds };
}

function featureBounds(feature) {
  const points = collectLngLatPairs(feature.geometry?.coordinates || []);
  const lngValues = points.map((point) => point[0]);
  const latValues = points.map((point) => point[1]);
  return {
    minLng: Math.min(...lngValues),
    maxLng: Math.max(...lngValues),
    minLat: Math.min(...latValues),
    maxLat: Math.max(...latValues)
  };
}

function featureContainsLngLat(feature, longitude, latitude) {
  const geometry = feature?.geometry || {};
  if (geometry.type === "Polygon") return polygonContainsLngLat(geometry.coordinates, longitude, latitude);
  if (geometry.type === "MultiPolygon") {
    return (geometry.coordinates || []).some((polygon) => polygonContainsLngLat(polygon, longitude, latitude));
  }
  return false;
}

function polygonContainsLngLat(polygon, longitude, latitude) {
  const [outerRing, ...holes] = polygon || [];
  if (!ringContainsLngLat(outerRing, longitude, latitude)) return false;
  return !holes.some((ring) => ringContainsLngLat(ring, longitude, latitude));
}

function ringContainsLngLat(ring, longitude, latitude) {
  if (!Array.isArray(ring) || ring.length < 3) return false;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const xi = Number(ring[i][0]);
    const yi = Number(ring[i][1]);
    const xj = Number(ring[j][0]);
    const yj = Number(ring[j][1]);
    const intersects = ((yi > latitude) !== (yj > latitude)) &&
      (longitude < ((xj - xi) * (latitude - yi)) / ((yj - yi) || 1e-9) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

const DEFAULT_VIEW = "agent";
const validViews = new Set(["overview", "agent", "policy", "workflow", "simulation", "analytics", "reports", "settings"]);
const validAnalyticsTabs = new Set(["overview", "periods", "external"]);

function readRouteState() {
  if (typeof window === "undefined") {
    return {
      view: DEFAULT_VIEW,
      analyticsTab: "overview",
      simulationId: "",
      tick: 0
    };
  }
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view") || DEFAULT_VIEW;
  const analyticsTab = params.get("analytics_tab") || params.get("analyticsTab") || "overview";
  const tick = Number(params.get("tick") || 0);
  return {
    view: validViews.has(view) ? view : DEFAULT_VIEW,
    analyticsTab: validAnalyticsTabs.has(analyticsTab) ? analyticsTab : "overview",
    simulationId: params.get("simulation_id") || params.get("simulationId") || "",
    tick: Number.isFinite(tick) ? tick : 0
  };
}

function navigateToView(viewKey) {
  if (!validViews.has(viewKey)) return;
  activeView.value = viewKey;
  if (viewKey === "policy") applyPolicyMappingStepFromUrl();
}

function syncRouteToUrl(options = {}) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("view", activeView.value || DEFAULT_VIEW);
  if (activeView.value === "analytics") {
    url.searchParams.set("analytics_tab", analyticsActiveTab.value || "overview");
  } else {
    url.searchParams.delete("analytics_tab");
  }
  if (activeView.value === "policy") {
    url.searchParams.set("policy_step", policyMappingWorkflowStep.value || "text");
  } else {
    url.searchParams.delete("policy_step");
  }
  if (simulationId.value) {
    url.searchParams.set("simulation_id", simulationId.value);
  } else {
    url.searchParams.delete("simulation_id");
  }
  if ((activeView.value === "simulation" || activeView.value === "analytics") && currentPlaybackTick.value) {
    url.searchParams.set("tick", String(currentPlaybackTick.value));
  } else {
    url.searchParams.delete("tick");
  }
  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  if (nextUrl === `${window.location.pathname}${window.location.search}${window.location.hash}`) return;
  const method = options.replace ? "replaceState" : "pushState";
  window.history[method]({}, "", nextUrl);
}

function applyRouteFromLocation() {
  const nextRoute = readRouteState();
  activeView.value = nextRoute.view;
  analyticsActiveTab.value = nextRoute.analyticsTab;
  simulationId.value = nextRoute.simulationId;
  if (nextRoute.tick) currentPlaybackTick.value = nextRoute.tick;
  if (nextRoute.view === "policy") applyPolicyMappingStepFromUrl();
}

function applyPolicyMappingStepFromUrl() {
  if (typeof window === "undefined") return;
  const routeStepKey = new URLSearchParams(window.location.search).get("policy_step");
  const stepKey = routeStepKey === "macro" ? "mechanism" : routeStepKey;
  const validStepKeys = new Set([...policyMappingWorkflow.map((step) => step.key), "rules"]);
  if (stepKey && validStepKeys.has(stepKey)) {
    openMappingWorkflowStep(stepKey, { syncUrl: false });
  }
}

const initialRouteState = readRouteState();
const activeView = ref(initialRouteState.view);
const agentTab = ref("agent");
const selectedAgentId = ref("C003");
const agentKeyword = ref("");
const enterpriseTypeFilter = ref("All");
const enterpriseTypeFilters = ["All", "Owner", "Contractor", "Architect", "Consultant", "Supplier"];
const agentDetailTabs = [
  { key: "profile", label: "Profile" },
  { key: "memory", label: "Memory" },
  { key: "belief", label: "Belief" },
  { key: "strategy", label: "Strategy" },
  { key: "trace", label: "Decision Trace" }
];
const enterpriseRegionFilter = ref("All Regions");
const enterpriseRegionOptions = ["All Regions", "广州", "深圳", "珠海", "佛山", "惠州", "东莞", "中山", "江门", "肇庆", "香港", "澳门"];
const agentPage = ref(1);
const agentPageSize = ref(48);
const agentTotal = ref(0);
const agentLoading = ref(false);
const selectedCluster = ref("GBA 1000 Enterprise Test Cluster");
const selectedPolicy = ref("Greater Bay Area Cross-Regional Collaboration Policy");
const policyKeyword = ref("");
const policyTypeFilter = ref("All");
const policyRegionFilter = ref("All Regions");
const policyLoading = ref(false);
const policyFiltersOpen = ref(false);
const policySummaryPanelOpen = ref(true);
const policyMappingTab = ref("library");
const policyMappingWorkflowStep = ref("text");
const selectedMappingPolicyId = ref("policy-hk-macao-coop");
const selectedMappingScenarioId = ref("S3");
const selectedMechanismPackageIds = ref([]);
const selectedAtomicInstrumentIds = ref([]);
const expandedMechanismPackageIds = ref([]);
const mechanismStrengthDraft = ref({});
const customAtomicRuleDraft = ref({});
const initializedMechanismPolicyId = ref("");
const selectedPolicyInstrumentId = ref("market_access");
const selectedPolicyExperimentId = ref("S1");
const policyExperimentGenerationVersion = ref(1);
const policyExperimentQuestionDraft = ref("");
const policyExperimentAppliedObjective = ref("");
const policyExperimentAppliedPlan = ref("");
const policyExperimentDesignStage = ref("question");
const policyExperimentPresetOpen = ref(false);
const policyExperimentCandidateDrafts = ref([]);
const policyExperimentConfirmedBlueprints = ref([]);
const policyCausalModalOpen = ref(false);
const policyCausalModal = ref(null);
const policyCustomRuleInput = ref(null);
const policyInterventionMapMode = ref("package");
const expandedPolicyModuleId = ref("");
const selectedMechanismPlanId = ref("balanced");
const backendOnline = ref(false);
const running = ref(false);
const workflowTicks = ref(60);
const workflowInspectorOpen = ref(true);
const useDatabaseAgents = ref(true);
const simulationAgentCount = ref(1000);
const maxTenderInvites = ref(40);
const usePriorNetworkEdges = ref(true);
const workflowRunStatus = ref("idle");
const workflowRunError = ref("");
const workflowRunResult = ref(null);
const selectedTimelineItemId = ref("policy-1");
const workflowTimelineTrack = ref(null);
const workflowTimelineDragState = ref(null);
const workflowPeriodHoverState = ref(null);
const workflowTemplateMessage = ref("");
const workflowTemplateMessageTone = ref("success");
const simulationId = ref(initialRouteState.simulationId);
const simulationResult = ref(null);
const performanceHistory = ref([]);
const networkData = ref({ nodes: [], edges: [] });
const metrics = ref({});
const backendAgents = ref([]);
const locallyCreatedAgents = ref([]);
const agentProfiles = ref({});
const agentCognitiveStates = ref({});
const agentCognitiveLoading = ref(false);
const agentDetailTab = ref("profile");
const backendClusters = ref([]);
const clusterDetails = ref({});
const backendPolicies = ref([]);
const policyDetails = ref({});
const policyPreview = ref(null);
const workflowData = ref(null);
const procurementReady = ref(false);
const integrationCaseId = ref("CASE-0005");
const integrationModelMode = ref("llm");
const integrationDataConsent = ref(false);
const procurementExecution = computed({
  get: () => workflowData.value?.configuration?.procurement_execution || {
    schema_version: "1.0", mode: "gba_native", scope: "full_procurement",
    adapter_profile_id: null, failure_policy: "pause"
  },
  set: value => { ensureWorkflowConfiguration().procurement_execution = value; }
});
const runtimeState = ref(null);
const playbackTimeline = ref([]);
const currentPlaybackTick = ref(initialRouteState.tick);
const simulationPlaying = ref(false);
const playbackSpeed = ref(1);
const selectedRuntimeEnterprise = ref(null);
const selectedRuntimeProject = ref(null);
const expandedProjectEventIds = ref(new Set());
const selectedEnterpriseHistory = ref(null);
const enterpriseHistoryLoading = ref(false);
const enterpriseActivityExpanded = ref(false);
const defaultEnterpriseSelectionLocked = ref(false);
const analyticsDashboard = ref(null);
const analyticsActiveTab = ref(initialRouteState.analyticsTab);
const analyticsFormulaTooltipOpen = ref("");
const analyticsTabs = [
  { key: "overview", label: "Overview" },
  { key: "periods", label: "Periods Analysis" },
  { key: "external", label: "External Change Analysis" }
];
const periodCompareMode = ref("monthly");
const periodInfoOpen = ref(false);
const externalFocusMode = ref("all");
const selectedExternalPolicyId = ref("policy-1");
const selectedExternalEventId = ref("event-1");
const selectedExternalWindowId = ref("during");
const periodFocusedTransitionIndex = ref(1);
const periodEvidenceTab = ref("trend");
const chatMessages = ref([]);
const chatInput = ref("");
const chatLoading = ref(false);
const agentModalOpen = ref(false);
const agentModalMode = ref("create");
const agentCreateSourceMode = ref("manual");
const uploadedAgentFiles = ref([]);
const agentForm = ref(defaultAgentForm());
const aiAgentForm = ref(defaultAiAgentForm());

const agentRadarRef = ref(null);
const clusterRadarRef = ref(null);
const clusterDonutRef = ref(null);
const policyRadarRef = ref(null);
const analyticsTrendRef = ref(null);
const analyticsNetworkRef = ref(null);
const analyticsRegionMapRef = ref(null);
const analyticsResourceFlowRef = ref(null);
const runtimeMapRef = ref(null);
const defaultRuntimeMapZoom = 1.21;
const defaultRuntimeMapPan = () => ({ x: 0, y: 0 });
const runtimeMapZoom = ref(defaultRuntimeMapZoom);
const runtimeMapPan = ref(defaultRuntimeMapPan());
const runtimeMapDragging = ref(false);
const selectedRuntimeRegion = ref("");
const selectedAnalyticsRegionName = ref("Shenzhen");
const hoveredRuntimeRegion = ref("");
const chartCache = new Map();
const runtimeMapFitZoom = 58;
const playbackSpeedOptions = [0.5, 1, 1.5, 2, 4];
const regionLabelScale = computed(() => Number((1 / Math.max(0.72, Math.min(2.4, runtimeMapZoom.value || 1))).toFixed(3)));
let playbackTimer = null;
let playbackRequestInFlight = false;
const runtimeMapDragState = {
  active: false,
  dragged: false,
  pointerId: null,
  startX: 0,
  startY: 0,
  originX: 0,
  originY: 0
};

const capabilitySections = [
  {
    title: "Core Enterprise",
    items: [
      { key: "qualificationLevel", label: "Qualification Level" },
      { key: "financialCapacity", label: "Financial Capacity" },
      { key: "technicalCapability", label: "Technical Capability" },
      { key: "managementCapability", label: "Management Capability" },
      { key: "totalResourceCapacity", label: "Resource Capacity" }
    ]
  },
  {
    title: "Collaboration",
    items: [
      { key: "riskPreference", label: "Risk Preference" },
      { key: "collaborationPreference", label: "Collaboration Preference" },
      { key: "crossRegionExperience", label: "Cross-region Experience" },
      { key: "policyAdaptability", label: "Policy Adaptability" },
      { key: "decisionSpeed", label: "Decision Speed" }
    ]
  },
  {
    title: "Role Performance",
    items: [
      { key: "designCapability", label: "Design Capability" },
      { key: "costEstimationCapability", label: "Cost Estimation" },
      { key: "constructionCapability", label: "Construction Capability" },
      { key: "qualityManagementCapability", label: "Quality Management" },
      { key: "safetyManagementCapability", label: "Safety Management" }
    ]
  },
  {
    title: "Project Reliability",
    items: [
      { key: "supervisionCapability", label: "Supervision Capability" },
      { key: "supplyReliability", label: "Supply Reliability" },
      { key: "materialQuality", label: "Material Quality" },
      { key: "paymentReliability", label: "Payment Reliability" }
    ]
  }
];

const navItems = [
  { key: "overview", label: "Overview", icon: Home },
  { key: "agent", label: "Agent", icon: UserRound },
  { key: "policy", label: "Policy", icon: Shield },
  { key: "workflow", label: "Workflow", icon: Workflow },
  { key: "simulation", label: "Simulation", icon: Package },
  { key: "analytics", label: "Analytics", icon: BarChart3 },
  { key: "reports", label: "Reports", icon: FileText },
  { key: "settings", label: "Setting", icon: Settings }
];

const staticAgents = [
  { agent_id: "O001", name: "Shenzhen Bay Owner", role: "Owner", region: "Shenzhen", rating: 4.5, projects: 71, ai_generated: false },
  { agent_id: "A001", name: "GBA Design Studio", role: "Architect", region: "Guangzhou", rating: 4.4, projects: 69, ai_generated: true },
  { agent_id: "Q001", name: "Pearl QS Consulting", role: "QS", region: "Hong Kong", rating: 4.3, projects: 65, ai_generated: false },
  { agent_id: "C001", name: "Guangdong Contractor A", role: "Contractor", region: "Guangzhou", rating: 4.2, projects: 60, ai_generated: false },
  { agent_id: "C002", name: "Hong Kong Contractor B", role: "Contractor", region: "Hong Kong", rating: 4.5, projects: 78, ai_generated: false },
  { agent_id: "C003", name: "Shenzhen Contractor C", role: "Contractor", region: "Shenzhen", rating: 4.6, projects: 82, ai_generated: false },
  { agent_id: "S001", name: "Foshan Supplier", role: "Supplier", region: "Foshan", rating: 4.1, projects: 62, ai_generated: false },
  { agent_id: "G001", name: "GBA Regulator", role: "Government", region: "Shenzhen", rating: 4.7, projects: 94, ai_generated: false }
];

const staticClusterRows = [
  { name: "Greater Bay Area Construction Cluster", type: "Regional Cluster", region: "GBA", size: 126, status: "Ready", tag: "Regional Mix" },
  { name: "Shenzhen Construction Enterprise Cluster", type: "City Cluster", region: "Shenzhen", size: 42, status: "Ready", tag: "High Activity" },
  { name: "Hong Kong Construction Enterprise Cluster", type: "City Cluster", region: "Hong Kong", size: 31, status: "Ready", tag: "International" },
  { name: "Guangzhou Construction Enterprise Cluster", type: "City Cluster", region: "Guangzhou", size: 38, status: "Ready", tag: "Comprehensive" },
  { name: "Cross-Border Project Delivery Cluster", type: "Mixed Cluster", region: "GBA", size: 29, status: "Ready", tag: "Cross-Regional" },
  { name: "Zhuhai Industrial & Supply Cluster", type: "Supplier Cluster", region: "Zhuhai", size: 18, status: "Draft", tag: "Manufacturing" }
];

const staticPolicyRows = [
  { name: "Greater Bay Area Cross-Regional Collaboration Policy", type: "Inter-regional", region: "GBA", status: "Active", params: 18, color: "orange", icon: Handshake },
  { name: "Low-Carbon Construction Incentive Scheme", type: "Sustainability", region: "Shenzhen", status: "Active", params: 16, color: "green", icon: Shield },
  { name: "Digital Construction Adoption Programme", type: "Technology", region: "Hong Kong", status: "Active", params: 20, color: "purple", icon: Package },
  { name: "Public Project Procurement Reform", type: "Governance", region: "Guangzhou", status: "Draft", params: 14, color: "blue", icon: Building2 },
  { name: "Green Building Retrofit Subsidy", type: "Sustainability", region: "Macau", status: "Pending", params: 15, color: "teal", icon: Building2 },
  { name: "Cross-Border Qualification Recognition Pilot", type: "Regulation", region: "Zhuhai", status: "Active", params: 17, color: "brown", icon: Network }
];

const policyMappingWorkflow = [
  { key: "text", label: "Policy Evidence Structuring", description: "Source & clauses" },
  { key: "mechanism", label: "Intervention Architecture & Quantification", description: "Tools, paths & parameters" },
  { key: "scenario", label: "Scenario Design & Generation", description: "Question, plans & runs" },
  { key: "review", label: "Review & Simulation Handoff", description: "Approval & handoff" }
];

const mappingWizardSteps = [
  {
    title: "Policy Evidence Structuring",
    description: "Preserve the source, segment clauses, assess evidence quality, and recommend the appropriate modeling route.",
    outputs: ["Source evidence", "Policy clauses", "Evidence quality"]
  },
  {
    title: "Intervention Architecture & Quantification",
    description: "Define intervention modules, atomic instruments, causal chains, direct variables, and instrument-level parameter changes.",
    outputs: ["Atomic instruments", "Causal chains", "Variables & deltas"]
  },
  {
    title: "Scenario Design & Generation",
    description: "Frame the research question, curate policy execution plans, then translate confirmed plans into comparison-ready simulation scenarios.",
    outputs: ["Research question", "Confirmed plans", "Scenario portfolio"]
  },
  {
    title: "Review & Simulation Handoff",
    description: "Resolve assumptions, approve the scenario portfolio, and generate one model-ready configuration for every execution pathway.",
    outputs: ["Review record", "Frozen scenario portfolio", "Simulation scenario package"]
  }
];

const mechanismStrengthOptions = [
  { key: "weak", label: "弱", description: "试点或方向性推进" },
  { key: "medium", label: "中", description: "常规配套落地" },
  { key: "strong", label: "强", description: "强配套或大范围推进" }
];

const mechanismStrengthLabelMap = {
  weak: "弱",
  medium: "中",
  strong: "强"
};

const policyUiDictionary = {
  "宏观政策文本": "Macro Policy Text",
  "政策文件、细则或政策设想": "Policy file, implementation rule, or policy concept",
  "目标机制识别": "Target & Mechanism Identification",
  "明确目标、对象和作用路径": "Define targets, actors, and mechanism paths",
  "变量量化映射": "Variable Quantification Mapping",
  "确定变量、方向和变化量": "Define variables, direction, and delta",
  "情景包生成": "Scenario Package Generation",
  "生成弱中强和组合方案": "Generate weak, medium, strong, and combined plans",
  "情景审核确认": "Scenario Review & Confirmation",
  "确认假设、来源和敏感项": "Confirm assumptions, sources, and sensitive items",
  "原子规则参数": "Atomic Rule Parameters",
  "接入 Agent 仿真模型": "Link to Agent Simulation Model",
  "弱": "Low",
  "中": "Medium",
  "强": "High",
  "低": "Low",
  "高": "High",
  "港澳合作": "Hong Kong-Macao Cooperation",
  "审批细则": "Approval Rules",
  "项目清单": "Project List",
  "资质规则": "Qualification Rules",
  "粤港澳大湾区": "Greater Bay Area",
  "大湾区": "Greater Bay Area",
  "深圳 / 横琴": "Shenzhen / Hengqin",
  "香港 / 澳门 / 内地": "Hong Kong / Macao / Mainland",
  "深化港澳合作政策仿真": "Deepen Hong Kong-Macao Cooperation Policy Simulation",
  "跨境重大项目供给评估": "Cross-Border Major Project Supply Assessment",
  "跨境资质互认影响评估": "Cross-Border Qualification Recognition Impact Assessment",
  "情景待确认": "Scenario Pending Confirmation",
  "规则已生成": "Rules Generated",
  "变量已生成": "Variables Generated",
  "待审核": "Needs Review",
  "已确认": "Confirmed",
  "直接进入": "Direct Entry",
  "派生解释": "Derived Explanation",
  "宏观推断": "Macro Inference",
  "机制推断": "Mechanism Inference",
  "系统推断": "System Inference",
  "政策明文": "Explicit Policy Text",
  "政策明文 + 情景补足": "Explicit Policy + Scenario Fill",
  "情景假设": "Scenario Assumption",
  "专家设定": "Expert Setting",
  "模型生成情景": "Model-Generated Scenario",
  "可选情景假设": "Optional Scenario Assumption",
  "历史基准": "Historical Baseline",
  "历史数据": "Historical Data",
  "规则派生": "Rule-Derived",
  "宏观导向型": "Macro-Oriented",
  "混合型": "Hybrid",
  "具体规则型": "Concrete Rule",
  "宏观变量路径": "Macro Variable Path",
  "宏观变量 + 情景包路径": "Macro Variable + Scenario Package Path",
  "具体规则路径": "Concrete Rule Path",
  "情景包路径": "Scenario Package Path",
  "宏观变量为主，具体实施细则需通过情景包确认。": "Macro variables are primary; implementation details should be confirmed through scenario packages.",
  "具体规则较清晰，可直接转为原子规则参数。": "Concrete rules are clear enough to convert into atomic rule parameters.",
  "数字目标": "Numeric Target",
  "规则清晰": "Rule Clarity",
  "对象明确": "Target Clarity",
  "时间清晰": "Time Clarity",
  "资源清晰": "Resource Clarity",
  "政策信号增强": "Policy Signal Strengthening",
  "跨区域阻力下降": "Cross-Regional Barrier Reduction",
  "审批便利化": "Approval Facilitation",
  "项目供给预期提升": "Project Supply Expectation Increase",
  "审批等待下降": "Approval Waiting Time Reduction",
  "行政成本下降": "Administrative Cost Reduction",
  "项目供给增加": "Project Supply Increase",
  "联合体机会增加": "Consortium Opportunity Increase",
  "市场准入放宽": "Market Access Expansion",
  "资质转换成本下降": "Qualification Conversion Cost Reduction",
  "提升港澳企业对大湾区项目机会的感知，增加进入市场和寻找伙伴的概率。": "Increase Hong Kong and Macao firms' awareness of GBA project opportunities, market entry, and partner-search probability.",
  "通过规则衔接和机制对接降低跨境合作的不确定性和协作成本。": "Reduce uncertainty and coordination costs in cross-border collaboration through rule and mechanism alignment.",
  "绿色通道和审批时限压缩直接降低项目等待时间，间接提高投标意愿。": "Green-channel treatment and shorter approval deadlines reduce project waiting time and indirectly raise bid willingness.",
  "重大项目参与机会增加，带动跨境合作项目发布和联合体组织。": "More major-project opportunities drive cross-border project release and consortium formation.",
  "直接缩短审批等待时间，降低项目启动延迟。": "Directly shorten approval waiting time and reduce project start delay.",
  "线上申报减少材料准备和往返沟通成本。": "Online submission reduces material preparation and back-and-forth communication cost.",
  "新增清单提升跨境合作项目发布概率和项目规模。": "A new project list increases cross-border project release probability and project scale.",
  "联合体要求提高跨区域合作边数量和重复合作机会。": "Consortium requirements increase cross-region collaboration links and repeat cooperation opportunities.",
  "增加可参与项目的专业服务企业数量。": "Increase the number of professional service firms eligible to participate in projects.",
  "缩短认定周期，降低进入项目准备成本。": "Shorten recognition cycles and reduce project-entry preparation cost.",
  "市场准入便利包": "Market Access Facilitation Package",
  "市场准入": "Market Access",
  "市场开放机制": "Market Opening Mechanism",
  "审批流程便利包": "Approval Process Facilitation Package",
  "审批便利": "Approval Facilitation",
  "审批便利机制": "Approval Facilitation Mechanism",
  "资质互认扩大包": "Qualification Recognition Expansion Package",
  "资质互认": "Qualification Recognition",
  "资质互认机制": "Qualification Recognition Mechanism",
  "跨境项目供给包": "Cross-Border Project Supply Package",
  "项目供给": "Project Supply",
  "项目供给机制": "Project Supply Mechanism",
  "合作撮合平台包": "Partner Matching Platform Package",
  "合作撮合": "Partner Matching",
  "平台撮合机制": "Platform Matching Mechanism",
  "融资与资金支持包": "Financing & Funding Support Package",
  "资金支持": "Funding Support",
  "融资支持机制": "Financing Support Mechanism",
  "从“支持港澳企业参与”“放宽准入范围”等表述中生成准入便利情景。": "Generate access-facilitation scenarios from expressions such as supporting Hong Kong and Macao enterprise participation and easing access scope.",
  "由宏观政策目标和目标对象推断": "Inferred from macro policy goals and target roles",
  "把绿色通道、审批时限压缩、线上申报、并联审批转成流程参数。": "Convert green channel, approval deadline compression, online submission, and parallel review into process parameters.",
  "原文含“绿色通道”“审批时限压缩至10个工作日”": "Original text mentions green channel and approval deadline compressed to 10 working days",
  "将互认专业范围、办理周期和执业范围转为企业准入参数。": "Convert recognized profession scope, processing cycle, and practice scope into market-entry parameters.",
  "由“规则衔接”“机制对接”和资质互认政策联想生成": "Generated from rule alignment, mechanism alignment, and qualification-recognition policy analogy",
  "把重大项目参与、项目清单、可参与比例转成项目生成和项目匹配参数。": "Convert major-project participation, project list, and eligibility ratio into project generation and matching parameters.",
  "原文含“鼓励港澳企业参与大湾区重大项目建设”": "Original text mentions encouraging Hong Kong and Macao firms to participate in GBA major projects",
  "将撮合平台、伙伴推荐、联合体组织转成合作网络和匹配概率参数。": "Convert matching platforms, partner recommendations, and consortium organization into network and match-probability parameters.",
  "由规则衔接和合作网络目标推断": "Inferred from rule alignment and collaboration-network goals",
  "用于模拟专项资金、补贴比例、融资便利对企业收益的影响。": "Used to simulate how special funds, subsidy ratios, and financing facilitation affect firm returns.",
  "当前政策原文未明示，默认作为可选情景": "Not explicit in the current policy text; kept as an optional scenario",
  "小范围试点开放，主要影响政策信号和进入意愿。": "Small-scale pilot opening, mainly affecting policy signals and entry willingness.",
  "重点领域开放，形成可进入项目池。": "Open key fields and form an eligible project pool.",
  "多领域开放，并减少准入前置约束。": "Open multiple fields and reduce pre-entry constraints.",
  "绿色通道试点，审批时限轻度压缩。": "Pilot green-channel treatment with mild approval deadline compression.",
  "审批时限压缩至10个工作日，并启用线上申报。": "Compress approval deadline to 10 working days and enable online submission.",
  "审批时限压缩至7个工作日，启用全流程线上和并联审批。": "Compress approval deadline to 7 working days and enable full-process online plus parallel review.",
  "新增少量互认专业，仍以个案认定为主。": "Add a small number of recognized professions while keeping case-by-case recognition.",
  "新增5类互认专业，认定周期明显缩短。": "Add five recognized professions and shorten the recognition cycle.",
  "批量互认并扩大执业范围。": "Enable batch recognition and expand practice scope.",
  "新增少量跨境合作项目，偏试点。": "Add a small number of cross-border cooperation projects as a pilot.",
  "建立年度项目清单，跨境合作项目增加30%。": "Establish an annual project list and increase cross-border cooperation projects by 30%.",
  "动态项目库和多领域开放，供给增长50%。": "Dynamic project pool and multi-field opening, with supply growth of 50%.",
  "提供基础信息撮合，成功率小幅提升。": "Provide basic information matching with a mild increase in match success.",
  "建立合作撮合平台，撮合成功率提升至30%。": "Build a cooperation matching platform and raise match success to 30%.",
  "平台主动推荐伙伴并组织联合体。": "Platform actively recommends partners and organizes consortia.",
  "小规模补贴或融资撮合。": "Small-scale subsidy or financing matching.",
  "专项资金支持重点项目。": "Special funds support key projects.",
  "高强度补贴和融资便利。": "High-intensity subsidy and financing facilitation.",
  "港澳企业可参与项目比例": "HK/Macao Eligible Project Ratio",
  "准入前置审核": "Pre-Entry Review",
  "审批时限": "Approval Deadline",
  "线上申报": "Online Submission",
  "绿色通道": "Green Channel",
  "并联审批": "Parallel Review",
  "申报材料数量": "Required Material Count",
  "互认专业数量": "Recognized Profession Count",
  "资质认定周期": "Qualification Recognition Processing Days",
  "跨境项目供给增长率": "Cross-Border Project Supply Growth Rate",
  "重点项目清单": "Key Project List",
  "撮合成功率": "Matching Success Rate",
  "联合体推荐": "Consortium Recommendation",
  "平台撮合强度": "Platform Broker Power",
  "补贴比例": "Subsidy Rate",
  "企业准入": "Firm Entry",
  "项目审批": "Project Approval",
  "审批流程": "Approval Workflow",
  "行政成本": "Administrative Cost",
  "项目生成": "Project Generation",
  "合作网络": "Collaboration Network",
  "投标机制": "Bidding Mechanism",
  "企业收益": "Firm Return",
  "深化港澳合作若干措施": "Deepen Hong Kong-Macao Cooperation Measures",
  "港澳企业项目审批便利化细则": "HK/Macao Enterprise Project Approval Facilitation Rules",
  "重点跨境合作项目清单": "Key Cross-Border Cooperation Project List",
  "港澳专业资格互认办法": "HK/Macao Professional Qualification Recognition Measures",
  "围绕规则衔接、重大项目参与、审批便利化、资质互认和合作撮合，量化港澳企业参与项目和跨区域合作网络变化。": "Quantify how rule alignment, major-project participation, approval facilitation, qualification recognition, and partner matching affect HK/Macao enterprise participation and cross-regional collaboration networks.",
  "围绕绿色通道、线上申报和并联审批，直接量化项目审批周期、材料成本和项目启动效率。": "Quantify project approval cycle, material-preparation cost, and project start efficiency through green channel, online submission, and parallel review.",
  "把新增项目清单转成项目供给、项目类型、允许港澳企业参与范围和联合体要求。": "Convert a new project list into project supply, project type, HK/Macao eligibility scope, and consortium requirements.",
  "量化资质互认范围、认定周期和准入限制变化，评估港澳专业服务企业参与机会。": "Quantify qualification recognition scope, recognition cycle, and entry-limit changes to assess HK/Macao professional service participation opportunities.",
  "宏观方向评估": "Macro Direction Assessment",
  "审批便利优先": "Approval Facilitation First",
  "项目网络优先": "Project Network First",
  "综合推进基准": "Combined Implementation Baseline",
  "强实施上限": "Strong Implementation Upper Bound",
  "宏观参数主导": "Macro-Parameter Led",
  "单机制优先": "Single-Mechanism First",
  "组合机制优先": "Combined Mechanism First",
  "综合政策包": "Integrated Policy Package",
  "上限测试": "Upper-Bound Test",
  "低细化": "Low Detail",
  "中高细化": "Medium-High Detail",
  "中细化": "Medium Detail",
  "高细化": "High Detail",
  "适合政策只有宏观表述时，先保留政策信号、市场开放和合作预期，不强行细化不存在的规则。": "Use this when a policy is mostly macro-level: keep policy signal, market opening, and cooperation expectation without inventing unsupported rules.",
  "优先把绿色通道、审批时限、线上申报落成规则，适合验证短期项目效率提升。": "Prioritize green channel, approval deadline, and online submission rules to test short-term project-efficiency gains.",
  "强调项目清单、跨境项目供给和合作撮合，适合比较网络效应。": "Emphasize project lists, cross-border project supply, and partner matching to compare network effects.",
  "审批、资质、项目供给、撮合共同推进，作为正式研究的默认中等方案。": "Jointly advance approval, qualification, project supply, and matching as the default medium plan for formal study.",
  "强配套政策组合，用于测试效果上限、成本和风险。": "Use a strong support-policy bundle to test effect upper bound, cost, and risk.",
  "宏观推断为主": "Mostly Macro Inference",
  "政策明文 + 情景补足": "Explicit Policy + Scenario Fill",
  "情景假设 + 系统推断": "Scenario Assumption + System Inference",
  "明文规则 + 专家设定 + 情景假设": "Explicit Rules + Expert Setting + Scenario Assumption",
  "情景假设占比较高": "High Scenario-Assumption Share",
  "方向是否有效": "Direction Validity",
  "企业响应弹性": "Firm Response Elasticity",
  "宏观残差": "Macro Residual",
  "审批等待时间": "Approval Waiting Time",
  "项目启动周期": "Project Start Cycle",
  "重复计算检查": "Duplicate-Effect Check",
  "网络密度": "Network Density",
  "伙伴搜索": "Partner Search",
  "联合投标": "Joint Bidding",
  "总体效果": "Overall Effect",
  "机制贡献": "Mechanism Contribution",
  "敏感参数": "Sensitive Parameters",
  "效果上限": "Effect Upper Bound",
  "执行成本": "Implementation Cost",
  "敏感性分析": "Sensitivity Analysis",
  "基准情景": "Baseline Scenario",
  "弱实施情景": "Weak Implementation Scenario",
  "中等实施情景": "Medium Implementation Scenario",
  "强实施情景": "Strong Implementation Scenario",
  "审批便利单机制": "Approval-Only Mechanism Scenario",
  "10日审批情景": "10-Day Approval Scenario",
  "7日审批情景": "7-Day Approval Scenario",
  "清单发布情景": "Project List Release Scenario",
  "中等互认情景": "Medium Recognition Scenario",
  "不引入新增政策工具，用于对照政策效果。": "No new policy tool is introduced; this is used as the counterfactual baseline.",
  "政策信号增强，但具体配套工具有限，适合早期讨论。": "Policy signal increases with limited supporting tools; suitable for early discussion.",
  "审批便利、项目供给、资质互认和合作撮合均有中等力度推进。": "Approval facilitation, project supply, qualification recognition, and partner matching are implemented at medium intensity.",
  "强配套政策组合，检验政策上限和执行风险。": "Strong support-policy bundle to test effect ceiling and implementation risk.",
  "只开启审批便利，拆分审批机制对项目效率的贡献。": "Only approval facilitation is activated to isolate its contribution to project efficiency.",
  "审批时限压缩至10个工作日，启用线上申报。": "Approval deadline is compressed to 10 working days and online submission is enabled.",
  "审批时限压缩至7个工作日，并启用并联审批。": "Approval deadline is compressed to 7 working days and parallel review is enabled.",
  "新增30%跨境合作项目，允许更多港澳企业参与。": "Increase cross-border cooperation projects by 30% and allow more HK/Macao firms to participate.",
  "新增5类互认专业，认定周期缩短35%。": "Add five recognized professions and shorten the recognition cycle by 35%.",
  "基准": "Baseline",
  "政策信号": "Policy Signal",
  "轻度撮合": "Light Matching",
  "审批便利": "Approval Facilitation",
  "项目供给": "Project Supply",
  "资质互认": "Qualification Recognition",
  "合作撮合": "Partner Matching",
  "强审批便利": "Strong Approval Facilitation",
  "强项目供给": "Strong Project Supply",
  "平台撮合": "Platform Matching",
  "资金支持": "Funding Support",
  "线上申报": "Online Submission",
  "项目清单": "Project List",
  "联合体": "Consortium",
  "周期缩短": "Cycle Reduction",
  "政策信号强度": "Policy Signal Strength",
  "香港企业市场开放度": "Hong Kong Firm Market Openness",
  "合作撮合效率": "Partner Matching Efficiency",
  "跨区域合作阻力": "Cross-Regional Collaboration Barrier",
  "审批摩擦": "Approval Friction",
  "香港企业参与倾向": "Hong Kong Firm Participation Propensity",
  "跨境项目供给": "Cross-Border Project Supply",
  "联合投标概率": "Joint Bid Probability",
  "资质壁垒": "Qualification Barrier",
  "专业服务企业进入率": "Professional Service Firm Entry Rate",
  "审批时限减少": "Approval Deadline Reduction",
  "项目供给增加": "Project Supply Increase",
  "合作撮合成功率": "Matching Success Rate",
  "资质互认范围": "Qualification Recognition Scope",
  "跨境合作项目": "Cross-Border Cooperation Projects",
  "材料数量": "Material Count",
  "并联审批": "Parallel Review",
  "联合体比例": "Consortium Share",
  "互认专业": "Recognized Professions",
  "认定周期": "Recognition Cycle",
  "维持20个工作日": "Remain at 20 working days",
  "成功率维持18%": "Success rate remains at 18%",
  "提升至30%": "Increase to 30%",
  "新增5类专业": "Add 5 profession classes",
  "审批时限压缩比例需要确认": "Approval Deadline Reduction Ratio Requires Confirmation",
  "partner_matching_efficiency 来源为情景假设": "partner_matching_efficiency Uses Scenario Assumption",
  "项目供给增加比例敏感": "Project Supply Growth Ratio Is Sensitive",
  "并联审批是否同步实施": "Confirm Whether Parallel Review Is Implemented",
  "项目清单缺少真实项目数量": "Project List Lacks Real Project Count",
  "联合体比例为专家设定": "Consortium Share Is Expert-Set",
  "互认范围缺少真实文件依据": "Recognition Scope Lacks Documentary Evidence",
  "中等情景采用10个工作日，强实施情景采用7个工作日，需合作方确认是否符合现实约束。": "The medium scenario uses 10 working days and the strong scenario uses 7 working days; partners need to confirm feasibility.",
  "当前由合作撮合平台设定推导，缺少历史撮合成功率校准。": "Currently derived from the matching-platform setting and lacks historical match-success calibration.",
  "project_supply_growth_rate 对港澳企业参与项目数影响较大，建议进入敏感性分析。": "project_supply_growth_rate strongly affects HK/Macao enterprise participation and should enter sensitivity analysis.",
  "文本未明确所有项目均启用并联审批，需要确认适用范围。": "The text does not state that all projects use parallel review; scope needs confirmation.",
  "当前以增长率模拟，需要导入真实项目清单后校准。": "Currently simulated as a growth rate; calibrate after importing a real project list.",
  "需确认清单中要求联合体参与的项目占比。": "Confirm the share of listed projects requiring consortium participation.",
  "需要补充互认专业清单或专家确认。": "Supplement the recognized-profession list or obtain expert confirmation.",
  "新增中等实施情景和单机制审批消融": "Added medium implementation scenario and approval-only ablation",
  "补充资质互认和项目供给变量": "Added qualification recognition and project supply variables",
  "完成政策条款初始拆解": "Completed initial policy-clause decomposition",
  "补充并联审批参数": "Added parallel-review parameter",
  "完成审批时限和线上申报抽取": "Extracted approval deadline and online-submission rules",
  "形成项目供给和联合体变量": "Generated project supply and consortium variables",
  "形成资质壁垒和互认范围变量": "Generated qualification barrier and recognition-scope variables",
  "港澳企业参与项目数": "HK/Macao Enterprise Participating Projects",
  "联合投标数量": "Joint Bid Count",
  "跨区域网络密度": "Cross-Regional Network Density",
  "合作失败率": "Cooperation Failure Rate",
  "跨境合作项目数量": "Cross-Border Cooperation Project Count",
  "专业服务企业参与率": "Professional Service Firm Participation Rate",
  "准入等待时间": "Entry Waiting Time",
  "跨区域合作边": "Cross-Regional Collaboration Edges",
  "政策条款": "Policy Clauses",
  "外部变化": "External Change",
  "变量 / 规则": "Variables / Rules",
  "Agent行为": "Agent Behavior",
  "输出指标": "Output Metrics",
  "3条关键条款": "3 key clauses",
  "2条审批规则": "2 approval rules",
  "2条项目供给条款": "2 project-supply clauses",
  "2条资质规则": "2 qualification rules",
  "审批便利、项目供给、规则衔接": "approval facilitation, project supply, rule alignment",
  "审批时限和申报方式改变": "approval deadline and submission mode changes",
  "项目清单和联合体机会": "project list and consortium opportunities",
  "资质互认和认定周期缩短": "qualification recognition and shorter recognition cycle",
  "4个宏观变量 + 5个原子规则": "4 macro variables + 5 atomic rules",
  "3个原子规则": "3 atomic rules",
  "2个宏观变量 + 2个规则": "2 macro variables + 2 rules",
  "2个变量 + 2个规则": "2 variables + 2 rules",
  "参与、撮合、联合投标、项目启动": "participation, matching, joint bidding, project start",
  "更快启动项目和投标准备": "faster project start and bid preparation",
  "项目发布、联合投标、伙伴搜索": "project release, joint bidding, partner search",
  "准入、参与项目、寻找伙伴": "market entry, project participation, partner search",
  "项目参与、效率、网络密度、风险": "participation, efficiency, network density, risk",
  "审批等待、启动周期、失败率": "approval waiting time, start cycle, failure rate",
  "项目数量、投标数量、网络密度": "project count, bid count, network density",
  "参与率、等待时间、合作边": "participation rate, waiting time, collaboration edges",
  "工作日": "working days",
  "天": "days",
  "项": "items",
  "类": "classes"
};

function policyUi(value) {
  if (value === undefined || value === null) return "";
  const text = String(value);
  if (!text) return "";
  if (policyUiDictionary[text]) return policyUiDictionary[text];
  return text
    .replace(/、/g, ", ")
    .replace(/个工作日/g, " working days")
    .replace(/工作日/g, " working days")
    .replace(/20日/g, "20 days")
    .replace(/10日/g, "10 days")
    .replace(/7日/g, "7 days")
    .replace(/5类/g, "5 classes")
    .replace(/3类/g, "3 classes")
    .replace(/12项/g, "12 items")
    .replace(/8项/g, "8 items")
    .replace(/政策明文/g, "Explicit Policy Text")
    .replace(/情景补足/g, "Scenario Fill")
    .replace(/情景假设/g, "Scenario Assumption")
    .replace(/专家设定/g, "Expert Setting")
    .replace(/系统推断/g, "System Inference")
    .replace(/宏观推断/g, "Macro Inference")
    .replace(/机制推断/g, "Mechanism Inference")
    .replace(/历史数据/g, "Historical Data")
    .replace(/历史基准/g, "Historical Baseline")
    .replace(/已确认/g, "Confirmed")
    .replace(/待审核/g, "Needs Review")
    .replace(/直接进入/g, "Direct Entry")
    .replace(/派生解释/g, "Derived Explanation")
    .replace(/上升/g, "Increase")
    .replace(/下降/g, "Decrease");
}

function policyUiList(values) {
  return (values || []).map((value) => policyUi(value)).join(", ");
}

const defaultImplementationPackages = [
  {
    id: "market_access",
    name: "市场准入便利包",
    shortName: "市场准入",
    mechanism: "市场开放机制",
    description: "从“支持港澳企业参与”“放宽准入范围”等表述中生成准入便利情景。",
    evidence: "由宏观政策目标和目标对象推断",
    sourceType: "宏观推断",
    sourceTone: "inference",
    defaultSelected: true,
    defaultStrength: "medium",
    macroVariables: ["market_openness_hk", "market_openness_macao", "cross_region_barrier"],
    levels: {
      weak: {
        summary: "小范围试点开放，主要影响政策信号和进入意愿。",
        rules: [
          { id: "eligible_project_ratio_hk_macao", name: "港澳企业可参与项目比例", before: "0.20", after: "0.30", unit: "", source: "情景假设", confidence: "0.55", module: "企业准入", status: "待审核", statusTone: "review" }
        ]
      },
      medium: {
        summary: "重点领域开放，形成可进入项目池。",
        rules: [
          { id: "eligible_project_ratio_hk_macao", name: "港澳企业可参与项目比例", before: "0.20", after: "0.45", unit: "", source: "情景假设", confidence: "0.58", module: "企业准入", status: "待审核", statusTone: "review" },
          { id: "market_entry_review_required", name: "准入前置审核", before: "true", after: "false", unit: "", source: "专家设定", confidence: "0.62", module: "企业准入", status: "待审核", statusTone: "review" }
        ]
      },
      strong: {
        summary: "多领域开放，并减少准入前置约束。",
        rules: [
          { id: "eligible_project_ratio_hk_macao", name: "港澳企业可参与项目比例", before: "0.20", after: "0.65", unit: "", source: "情景假设", confidence: "0.54", module: "企业准入", status: "待审核", statusTone: "review" },
          { id: "market_entry_review_required", name: "准入前置审核", before: "true", after: "false", unit: "", source: "专家设定", confidence: "0.62", module: "企业准入", status: "待审核", statusTone: "review" }
        ]
      }
    }
  },
  {
    id: "approval",
    name: "审批流程便利包",
    shortName: "审批便利",
    mechanism: "审批便利机制",
    description: "把绿色通道、审批时限压缩、线上申报、并联审批转成流程参数。",
    evidence: "原文含“绿色通道”“审批时限压缩至10个工作日”",
    sourceType: "政策明文 + 情景补足",
    sourceTone: "explicit",
    defaultSelected: true,
    defaultStrength: "medium",
    macroVariables: ["approval_friction", "implementation_strength"],
    levels: {
      weak: {
        summary: "绿色通道试点，审批时限轻度压缩。",
        rules: [
          { id: "approval_deadline_days", name: "审批时限", before: "20", after: "15", unit: "工作日", source: "情景假设", confidence: "0.60", module: "项目审批", status: "待审核", statusTone: "review" },
          { id: "online_submission_enabled", name: "线上申报", before: "false", after: "partial", unit: "", source: "情景假设", confidence: "0.58", module: "行政成本", status: "待审核", statusTone: "review" }
        ]
      },
      medium: {
        summary: "审批时限压缩至10个工作日，并启用线上申报。",
        rules: [
          { id: "approval_deadline_days", name: "审批时限", before: "20", after: "10", unit: "工作日", source: "政策明文", confidence: "0.95", module: "项目审批", status: "已确认", statusTone: "ready" },
          { id: "green_channel_enabled", name: "绿色通道", before: "false", after: "true", unit: "", source: "政策明文", confidence: "0.90", module: "审批流程", status: "已确认", statusTone: "ready" },
          { id: "online_submission_enabled", name: "线上申报", before: "false", after: "true", unit: "", source: "情景假设", confidence: "0.62", module: "行政成本", status: "待审核", statusTone: "review" }
        ]
      },
      strong: {
        summary: "审批时限压缩至7个工作日，启用全流程线上和并联审批。",
        rules: [
          { id: "approval_deadline_days", name: "审批时限", before: "20", after: "7", unit: "工作日", source: "情景假设", confidence: "0.56", module: "项目审批", status: "待审核", statusTone: "review" },
          { id: "green_channel_enabled", name: "绿色通道", before: "false", after: "true", unit: "", source: "政策明文", confidence: "0.90", module: "审批流程", status: "已确认", statusTone: "ready" },
          { id: "parallel_review_enabled", name: "并联审批", before: "false", after: "true", unit: "", source: "专家设定", confidence: "0.68", module: "审批流程", status: "待审核", statusTone: "review" },
          { id: "required_material_count", name: "申报材料数量", before: "12", after: "5", unit: "项", source: "情景假设", confidence: "0.55", module: "行政成本", status: "待审核", statusTone: "review" }
        ]
      }
    }
  },
  {
    id: "qualification",
    name: "资质互认扩大包",
    shortName: "资质互认",
    mechanism: "资质互认机制",
    description: "将互认专业范围、办理周期和执业范围转为企业准入参数。",
    evidence: "由“规则衔接”“机制对接”和资质互认政策联想生成",
    sourceType: "专家设定",
    sourceTone: "expert",
    defaultSelected: true,
    defaultStrength: "medium",
    macroVariables: ["qualification_barrier", "professional_service_entry_rate"],
    levels: {
      weak: {
        summary: "新增少量互认专业，仍以个案认定为主。",
        rules: [
          { id: "recognized_profession_count", name: "互认专业数量", before: "3", after: "5", unit: "类", source: "专家设定", confidence: "0.62", module: "企业准入", status: "待审核", statusTone: "review" }
        ]
      },
      medium: {
        summary: "新增5类互认专业，认定周期明显缩短。",
        rules: [
          { id: "recognized_profession_count", name: "互认专业数量", before: "3", after: "8", unit: "类", source: "专家设定", confidence: "0.60", module: "企业准入", status: "待审核", statusTone: "review" },
          { id: "recognition_processing_days", name: "资质认定周期", before: "60", after: "30", unit: "天", source: "专家设定", confidence: "0.60", module: "企业准入", status: "待审核", statusTone: "review" }
        ]
      },
      strong: {
        summary: "批量互认并扩大执业范围。",
        rules: [
          { id: "recognized_profession_count", name: "互认专业数量", before: "3", after: "13", unit: "类", source: "情景假设", confidence: "0.52", module: "企业准入", status: "待审核", statusTone: "review" },
          { id: "recognition_processing_days", name: "资质认定周期", before: "60", after: "15", unit: "天", source: "情景假设", confidence: "0.52", module: "企业准入", status: "待审核", statusTone: "review" }
        ]
      }
    }
  },
  {
    id: "project_supply",
    name: "跨境项目供给包",
    shortName: "项目供给",
    mechanism: "项目供给机制",
    description: "把重大项目参与、项目清单、可参与比例转成项目生成和项目匹配参数。",
    evidence: "原文含“鼓励港澳企业参与大湾区重大项目建设”",
    sourceType: "情景假设",
    sourceTone: "assumption",
    defaultSelected: true,
    defaultStrength: "medium",
    macroVariables: ["cross_border_project_supply", "joint_bid_probability"],
    levels: {
      weak: {
        summary: "新增少量跨境合作项目，偏试点。",
        rules: [
          { id: "project_supply_growth_rate", name: "跨境项目供给增长率", before: "0", after: "0.10", unit: "", source: "情景假设", confidence: "0.58", module: "项目生成", status: "待审核", statusTone: "review" }
        ]
      },
      medium: {
        summary: "建立年度项目清单，跨境合作项目增加30%。",
        rules: [
          { id: "project_supply_growth_rate", name: "跨境项目供给增长率", before: "0", after: "0.30", unit: "", source: "情景假设", confidence: "0.58", module: "项目生成", status: "待审核", statusTone: "review" },
          { id: "key_project_list_enabled", name: "重点项目清单", before: "false", after: "true", unit: "", source: "情景假设", confidence: "0.60", module: "项目生成", status: "待审核", statusTone: "review" }
        ]
      },
      strong: {
        summary: "动态项目库和多领域开放，供给增长50%。",
        rules: [
          { id: "project_supply_growth_rate", name: "跨境项目供给增长率", before: "0", after: "0.50", unit: "", source: "情景假设", confidence: "0.50", module: "项目生成", status: "待审核", statusTone: "review" },
          { id: "key_project_list_enabled", name: "重点项目清单", before: "false", after: "dynamic_pool", unit: "", source: "专家设定", confidence: "0.56", module: "项目生成", status: "待审核", statusTone: "review" }
        ]
      }
    }
  },
  {
    id: "matching_platform",
    name: "合作撮合平台包",
    shortName: "合作撮合",
    mechanism: "平台撮合机制",
    description: "将撮合平台、伙伴推荐、联合体组织转成合作网络和匹配概率参数。",
    evidence: "由规则衔接和合作网络目标推断",
    sourceType: "系统推断",
    sourceTone: "inference",
    defaultSelected: true,
    defaultStrength: "medium",
    macroVariables: ["partner_matching_efficiency", "network_trust_growth"],
    levels: {
      weak: {
        summary: "提供基础信息撮合，成功率小幅提升。",
        rules: [
          { id: "partner_matching_success_rate", name: "撮合成功率", before: "0.18", after: "0.24", unit: "", source: "系统推断", confidence: "0.56", module: "合作网络", status: "待审核", statusTone: "review" }
        ]
      },
      medium: {
        summary: "建立合作撮合平台，撮合成功率提升至30%。",
        rules: [
          { id: "partner_matching_success_rate", name: "撮合成功率", before: "0.18", after: "0.30", unit: "", source: "专家设定", confidence: "0.64", module: "合作网络", status: "待审核", statusTone: "review" },
          { id: "joint_bid_recommendation_enabled", name: "联合体推荐", before: "false", after: "true", unit: "", source: "情景假设", confidence: "0.58", module: "投标机制", status: "待审核", statusTone: "review" }
        ]
      },
      strong: {
        summary: "平台主动推荐伙伴并组织联合体。",
        rules: [
          { id: "partner_matching_success_rate", name: "撮合成功率", before: "0.18", after: "0.40", unit: "", source: "情景假设", confidence: "0.52", module: "合作网络", status: "待审核", statusTone: "review" },
          { id: "joint_bid_recommendation_enabled", name: "联合体推荐", before: "false", after: "true", unit: "", source: "情景假设", confidence: "0.58", module: "投标机制", status: "待审核", statusTone: "review" },
          { id: "platform_broker_power", name: "平台撮合强度", before: "0.20", after: "0.70", unit: "", source: "模型生成情景", confidence: "0.50", module: "Government", status: "待审核", statusTone: "review" }
        ]
      }
    }
  },
  {
    id: "funding",
    name: "融资与资金支持包",
    shortName: "资金支持",
    mechanism: "融资支持机制",
    description: "用于模拟专项资金、补贴比例、融资便利对企业收益的影响。",
    evidence: "当前政策原文未明示，默认作为可选情景",
    sourceType: "可选情景假设",
    sourceTone: "assumption",
    defaultSelected: false,
    defaultStrength: "weak",
    macroVariables: ["funding_support_intensity", "expected_project_return"],
    levels: {
      weak: {
        summary: "小规模补贴或融资撮合。",
        rules: [
          { id: "subsidy_rate", name: "补贴比例", before: "0", after: "0.05", unit: "", source: "可选情景假设", confidence: "0.48", module: "企业收益", status: "待审核", statusTone: "review" }
        ]
      },
      medium: {
        summary: "专项资金支持重点项目。",
        rules: [
          { id: "subsidy_rate", name: "补贴比例", before: "0", after: "0.10", unit: "", source: "可选情景假设", confidence: "0.46", module: "企业收益", status: "待审核", statusTone: "review" }
        ]
      },
      strong: {
        summary: "高强度补贴和融资便利。",
        rules: [
          { id: "subsidy_rate", name: "补贴比例", before: "0", after: "0.20", unit: "", source: "可选情景假设", confidence: "0.42", module: "企业收益", status: "待审核", statusTone: "review" }
        ]
      }
    }
  }
];

const policyImplementationPackageMap = {
  "policy-hk-macao-coop": ["market_access", "approval", "qualification", "project_supply", "matching_platform", "funding"],
  "policy-approval-fast-track": ["approval", "market_access"],
  "policy-project-supply": ["project_supply", "matching_platform", "market_access"],
  "policy-qualification-recognition": ["qualification", "market_access", "matching_platform"]
};

const mechanismCombinationPlans = [
  {
    id: "macro_direction",
    name: "宏观方向评估",
    type: "宏观参数主导",
    detailLevel: "低细化",
    specificityScore: "0.28",
    scenarioId: "S2",
    summary: "适合政策只有宏观表述时，先保留政策信号、市场开放和合作预期，不强行细化不存在的规则。",
    packageStrengths: {
      market_access: "weak",
      matching_platform: "weak",
      project_supply: "weak"
    },
    sourceMix: "宏观推断为主",
    evaluationFocus: ["方向是否有效", "企业响应弹性", "宏观残差"],
    expected: { participation: "+12%", efficiency: "-4%", network: "+8%", risk: "低" }
  },
  {
    id: "approval_first",
    name: "审批便利优先",
    type: "单机制优先",
    detailLevel: "中高细化",
    specificityScore: "0.72",
    scenarioId: "S5",
    summary: "优先把绿色通道、审批时限、线上申报落成规则，适合验证短期项目效率提升。",
    packageStrengths: {
      approval: "strong",
      market_access: "medium",
      project_supply: "weak"
    },
    sourceMix: "政策明文 + 情景补足",
    evaluationFocus: ["审批等待时间", "项目启动周期", "重复计算检查"],
    expected: { participation: "+18%", efficiency: "-32%", network: "+7%", risk: "中" }
  },
  {
    id: "project_network",
    name: "项目网络优先",
    type: "供给与合作优先",
    detailLevel: "中细化",
    specificityScore: "0.56",
    scenarioId: "S3",
    summary: "优先增加项目清单和撮合平台，检验跨区域合作网络和联合投标的增长。",
    packageStrengths: {
      project_supply: "strong",
      matching_platform: "medium",
      market_access: "medium"
    },
    sourceMix: "情景假设 + 系统推断",
    evaluationFocus: ["跨境项目数量", "联合投标", "网络密度"],
    expected: { participation: "+24%", efficiency: "-8%", network: "+24%", risk: "中" }
  },
  {
    id: "balanced",
    name: "综合推进基准",
    type: "混合方案",
    detailLevel: "中细化",
    specificityScore: "0.64",
    scenarioId: "S3",
    summary: "审批、资质、项目供给和撮合平台同步推进，适合作为正式对比的中等实施方案。",
    packageStrengths: {
      approval: "medium",
      qualification: "medium",
      project_supply: "medium",
      matching_platform: "medium",
      market_access: "medium"
    },
    sourceMix: "明文规则 + 专家设定 + 情景假设",
    evaluationFocus: ["机制贡献分解", "中期网络变化", "综合政策收益"],
    expected: { participation: "+28%", efficiency: "-18%", network: "+22%", risk: "中" }
  },
  {
    id: "strong_integrated",
    name: "强实施上限",
    type: "压力测试",
    detailLevel: "高细化",
    specificityScore: "0.78",
    scenarioId: "S4",
    summary: "多机制强配套，用于测试政策效果上限，同时暴露假设风险和执行成本。",
    packageStrengths: {
      approval: "strong",
      qualification: "strong",
      project_supply: "strong",
      matching_platform: "strong",
      market_access: "strong",
      funding: "medium"
    },
    sourceMix: "情景假设占比较高",
    evaluationFocus: ["效果上限", "执行成本", "敏感性分析"],
    expected: { participation: "+42%", efficiency: "-28%", network: "+35%", risk: "高" }
  }
];

const policyExperimentBlueprints = [
  {
    key: "baseline",
    id: "S0",
    name: "Current Practice Baseline",
    type: "Reference",
    tone: "control",
    scenarioId: "S0",
    narrative: "Existing cross-border participation, approval, and partner-search arrangements continue without the new cooperation measures.",
    hypothesis: "This scenario provides the no-new-policy trajectory against which every execution pathway is evaluated.",
    packageStrengths: {},
    coverage: "Existing GBA arrangements",
    deliveryMode: "Current fragmented channels",
    enterpriseResponse: "Observed baseline behavior",
    rolloutTiming: "No additional rollout",
    feedback: ["Current application propensity", "Current approval capacity", "No new platform reinforcement"],
    contrast: "Reference",
    compareTo: "Anchor for S1-S5",
    comparisonFocus: "Underlying trend without the new measures",
    resultReadout: "Establishes the participation, project-cycle, and collaboration trajectory without additional implementation.",
    decisionUse: "Use as the common counterfactual for all implementation scenarios.",
    primaryMetrics: ["Participation", "Project start cycle", "Network density"],
    guardrail: "Keep the same initial agents, project pipeline, random seeds, and simulation horizon as every policy scenario.",
    focusKeys: ["all"],
    priority: 100,
    compareKeys: []
  },
  {
    key: "full",
    id: "S1",
    name: "Comprehensive Coordinated Rollout",
    type: "Full rollout",
    tone: "integrated",
    scenarioId: "S4",
    narrative: "Rules alignment, qualification recognition, major-project access, the green channel, and partner matching are launched together across the GBA.",
    hypothesis: "A coordinated package removes barriers along the full participation journey and creates the policy's highest credible implementation effect.",
    packageStrengths: {
      market_access: "strong",
      approval: "medium",
      qualification: "medium",
      project_supply: "strong",
      matching_platform: "strong"
    },
    coverage: "GBA-wide · all eligible major projects",
    deliveryMode: "Joint government and platform delivery",
    enterpriseResponse: "High · active application and consortium formation",
    rolloutTiming: "Full launch from Month 1",
    feedback: ["Administrative capacity expands with demand", "Successful projects increase repeat participation", "Platform recommendations reinforce cross-region matching"],
    contrast: "S1 vs S0",
    compareTo: "Full policy potential",
    comparisonFocus: "Maximum credible benefit of coordinated implementation",
    resultReadout: "Shows the attainable participation and collaboration gain when institutions and enterprises both respond strongly.",
    decisionUse: "Assess whether a GBA-wide coordinated rollout justifies its implementation complexity and capacity needs.",
    primaryMetrics: ["HK/Macao participation", "Project starts", "Joint bids", "Regional reach"],
    guardrail: "Track approval backlog, network concentration, and delivery capacity while the package scales.",
    focusKeys: ["all"],
    priority: 95,
    compareKeys: ["baseline"]
  },
  {
    key: "digital",
    id: "S2",
    name: "Digital Gateway-Led Rollout",
    type: "Digital-first",
    tone: "digital",
    scenarioId: "S5",
    narrative: "The policy is delivered primarily through online application, a digital green channel, a shared project portal, and algorithm-assisted partner matching.",
    hypothesis: "High online participation can lower access and search costs quickly, even before deeper institutional alignment is complete.",
    packageStrengths: {
      market_access: "weak",
      approval: "medium",
      qualification: "weak",
      project_supply: "medium",
      matching_platform: "strong"
    },
    coverage: "GBA-wide online access",
    deliveryMode: "Single digital gateway and matching platform",
    enterpriseResponse: "High online uptake · weaker offline reach",
    rolloutTiming: "Platform opens at Month 1",
    feedback: ["80% of new HK/Macao applicants use the online channel", "Digital matches feed future recommendations", "Institutional recognition remains partially manual"],
    contrast: "S2 vs S1 / S0",
    compareTo: "Digital delivery trade-off",
    comparisonFocus: "Speed and reach gained from a platform-led implementation",
    resultReadout: "Tests whether a digital-first route captures most participation gains with fewer institutional changes.",
    decisionUse: "Choose this route when rapid, scalable access is more feasible than full cross-government coordination.",
    primaryMetrics: ["Online application share", "Processing time", "Qualified matches", "SME participation"],
    guardrail: "Monitor exclusion of firms with low digital readiness and unresolved qualification barriers.",
    focusKeys: ["digital", "efficiency", "participation"],
    priority: 72,
    compareKeys: ["full", "baseline"]
  },
  {
    key: "project",
    id: "S3",
    name: "Major-Project Participation Drive",
    type: "Project-led",
    tone: "project",
    scenarioId: "S3",
    narrative: "Government releases a large cross-border project pipeline and actively invites HK/Macao firms to form joint bids with mainland project owners and partners.",
    hypothesis: "Visible, bankable project opportunities can mobilize firms more effectively than broad policy signaling alone.",
    packageStrengths: {
      market_access: "medium",
      approval: "medium",
      qualification: "weak",
      project_supply: "strong",
      matching_platform: "strong"
    },
    coverage: "Priority infrastructure and public projects",
    deliveryMode: "Project list, targeted invitations, and consortium support",
    enterpriseResponse: "Strong among established firms · moderate among SMEs",
    rolloutTiming: "Project batches released every 6 months",
    feedback: ["Awarded projects increase future bid propensity", "Successful consortiums create repeat ties", "Participation concentrates around project-ready firms"],
    contrast: "S3 vs S2 / S0",
    compareTo: "Project pull versus digital access",
    comparisonFocus: "Whether concrete opportunities outperform channel facilitation",
    resultReadout: "Shows whether major-project supply creates more completed participation and durable partnerships than a digital gateway alone.",
    decisionUse: "Use when the policy objective prioritizes visible projects and joint delivery over broad market opening.",
    primaryMetrics: ["Participating projects", "Joint bid conversion", "Project value", "Repeat partnerships"],
    guardrail: "Check whether benefits are captured only by large incumbent firms or a few central regions.",
    focusKeys: ["project", "network", "participation"],
    priority: 70,
    compareKeys: ["digital", "baseline"]
  },
  {
    key: "low_response",
    id: "S4",
    name: "Full Policy, Weak Enterprise Response",
    type: "Adoption risk",
    tone: "risk",
    scenarioId: "S4",
    narrative: "Government implements the complete policy package, but firms remain cautious, platform use stays low, and successful cooperation does not trigger much repeat participation.",
    hypothesis: "Formal policy implementation alone may produce limited outcomes when enterprise expectations, trust, or internal capacity do not change.",
    packageStrengths: {
      market_access: "strong",
      approval: "medium",
      qualification: "medium",
      project_supply: "strong",
      matching_platform: "strong"
    },
    coverage: "Same GBA-wide coverage as S1",
    deliveryMode: "Complete government rollout",
    enterpriseResponse: "Low · only 25% of eligible firms respond",
    rolloutTiming: "Full launch from Month 1",
    feedback: ["Application propensity remains near baseline", "Platform recommendations have low acceptance", "Successful projects create little repeat participation"],
    contrast: "S4 vs S1",
    compareTo: "Enterprise response penalty",
    comparisonFocus: "How much policy value depends on firm adoption and trust",
    resultReadout: "Separates policy availability from actual uptake and reveals the implementation-to-response gap.",
    decisionUse: "Determine whether outreach, capability support, or stronger incentives are required before full rollout.",
    primaryMetrics: ["Eligible-to-applicant conversion", "Platform activation", "Project take-up", "Unused capacity"],
    guardrail: "Do not interpret weak outcomes as policy-design failure before checking enterprise awareness and readiness.",
    focusKeys: ["participation", "risk", "network"],
    priority: 68,
    compareKeys: ["full"]
  },
  {
    key: "pilot",
    id: "S5",
    name: "Phased Cross-Border Pilot",
    type: "Phased pilot",
    tone: "pilot",
    scenarioId: "S2",
    narrative: "The measures begin with selected major projects in Shenzhen, Hengqin, Hong Kong, and Macao before expanding to the wider GBA.",
    hypothesis: "A staged pilot can produce credible learning and control delivery risk, although network effects and regional reach develop more slowly.",
    packageStrengths: {
      market_access: "weak",
      approval: "medium",
      qualification: "weak",
      project_supply: "medium",
      matching_platform: "medium"
    },
    coverage: "Four pilot areas · selected project categories",
    deliveryMode: "Phased eligibility and project batches",
    enterpriseResponse: "Moderate · invited firms respond first",
    rolloutTiming: "12-month pilot, then conditional expansion",
    feedback: ["Learning improves approval capacity after each batch", "Network spillovers remain within pilot corridors", "Expansion requires conversion and backlog thresholds"],
    contrast: "S5 vs S1 / S0",
    compareTo: "Scale versus controllability",
    comparisonFocus: "Benefits retained under a lower-risk staged rollout",
    resultReadout: "Measures how much impact a controlled pilot preserves and what evidence is available before scaling.",
    decisionUse: "Use when implementation uncertainty is high and decision-makers need a credible scale-up gate.",
    primaryMetrics: ["Pilot conversion", "Backlog", "Time to learning", "Regional spillover"],
    guardrail: "Avoid generalizing pilot effects to the whole GBA before coverage and firm-mix differences are tested.",
    focusKeys: ["regional", "risk", "participation"],
    priority: 60,
    compareKeys: ["full", "baseline"]
  },
  {
    key: "approval_capacity",
    id: "S6",
    name: "Fast-Track with Fixed Administrative Capacity",
    type: "Capacity constrained",
    tone: "risk",
    scenarioId: "S5",
    narrative: "The 10-day green channel and online application are implemented broadly, but review staffing and interdepartmental capacity do not expand with demand.",
    hypothesis: "Process acceleration may initially improve starts but later create a queue if administrative capacity becomes the binding constraint.",
    packageStrengths: {
      market_access: "medium",
      approval: "strong",
      project_supply: "medium",
      matching_platform: "medium"
    },
    coverage: "GBA-wide eligible projects",
    deliveryMode: "Fast-track workflow with fixed staffing",
    enterpriseResponse: "High application response",
    rolloutTiming: "Immediate launch · no capacity ramp-up",
    feedback: ["Application volume rises faster than reviewer capacity", "Backlog delays spill into project starts", "Firms reduce repeat applications after long queues"],
    contrast: "Capacity comparison",
    compareTo: "Administrative bottleneck",
    comparisonFocus: "Whether approval capacity limits the benefit of a fast-track policy",
    resultReadout: "Reveals the point at which faster formal deadlines stop translating into faster project starts.",
    decisionUse: "Estimate the staffing and review-capacity requirement needed to sustain the policy promise.",
    primaryMetrics: ["Approval backlog", "Actual approval days", "Project starts", "Abandonment rate"],
    guardrail: "Distinguish stated deadlines from realized processing time under peak demand.",
    focusKeys: ["efficiency", "risk", "digital"],
    priority: 64,
    compareKeys: ["full"]
  },
  {
    key: "qualification_first",
    id: "S7",
    name: "Professional Qualification-First Rollout",
    type: "Recognition-led",
    tone: "digital",
    scenarioId: "S2",
    narrative: "Qualification recognition and entry rights are expanded first for architects, quantity surveyors, and consultants before the wider project and matching package is launched.",
    hypothesis: "Removing professional-entry barriers may increase specialist participation even without a broad increase in project supply.",
    packageStrengths: {
      market_access: "medium",
      approval: "weak",
      qualification: "strong",
      project_supply: "weak",
      matching_platform: "medium"
    },
    coverage: "Selected professional-service categories",
    deliveryMode: "Recognition registry and targeted matching",
    enterpriseResponse: "High among recognized specialists",
    rolloutTiming: "Profession batches every 6 months",
    feedback: ["Recognized specialists become eligible immediately", "Employers gradually learn to accept cross-border credentials", "Participation grows through specialist project teams"],
    contrast: "Recognition comparison",
    compareTo: "Qualification barrier removal",
    comparisonFocus: "Whether professional recognition is the binding constraint on participation",
    resultReadout: "Shows whether recognition-led implementation reaches specialist firms that broader project measures may miss.",
    decisionUse: "Prioritize formal recognition when the research objective focuses on professional-service entry.",
    primaryMetrics: ["Recognized professionals", "Professional firm entry", "Waiting time", "Specialist project participation"],
    guardrail: "Check employer acceptance as well as formal eligibility.",
    focusKeys: ["qualification", "participation"],
    priority: 62,
    compareKeys: ["full", "baseline"]
  }
];

const policyScenarioResearchFocusDefinitions = [
  {
    key: "efficiency",
    label: "Approval efficiency and delivery capacity",
    keywords: [/approval/i, /deadline/i, /processing/i, /time/i, /cycle/i, /backlog/i, /capacity/i, /审批/, /时限/, /效率/, /周期/, /积压/, /能力/],
    packageIds: ["approval", "market_access"],
    candidateKeys: ["approval_capacity", "digital", "pilot", "low_response"],
    metrics: ["Realized approval time", "Application backlog", "Project start cycle", "Abandonment rate"]
  },
  {
    key: "digital",
    label: "Digital access and online participation",
    keywords: [/digital/i, /online/i, /platform/i, /internet/i, /gateway/i, /线上/, /数字/, /平台/, /互联网/],
    packageIds: ["approval", "matching_platform", "project_supply"],
    candidateKeys: ["digital", "approval_capacity", "project", "low_response"],
    metrics: ["Online application share", "Digital reach", "Processing time", "Qualified matches"]
  },
  {
    key: "participation",
    label: "Enterprise participation and policy uptake",
    keywords: [/participation/i, /enterprise/i, /firm/i, /adoption/i, /uptake/i, /response/i, /参与/, /企业/, /响应/, /采纳/],
    packageIds: ["market_access", "project_supply", "matching_platform"],
    candidateKeys: ["digital", "project", "low_response", "pilot"],
    metrics: ["Eligible-to-applicant conversion", "Participating firms", "Repeat participation", "Regional reach"]
  },
  {
    key: "project",
    label: "Project opportunity and bid conversion",
    keywords: [/project/i, /opportunity/i, /pipeline/i, /bid/i, /supply/i, /项目/, /机会/, /清单/, /投标/, /供给/],
    packageIds: ["project_supply", "matching_platform", "market_access"],
    candidateKeys: ["project", "digital", "pilot", "low_response"],
    metrics: ["Open project pipeline", "Bid conversion", "Project starts", "Project value"]
  },
  {
    key: "qualification",
    label: "Qualification recognition and professional entry",
    keywords: [/qualification/i, /recognition/i, /professional/i, /credential/i, /资质/, /互认/, /专业/, /资格/],
    packageIds: ["qualification", "market_access", "matching_platform"],
    candidateKeys: ["qualification_first", "digital", "pilot", "low_response"],
    metrics: ["Recognized professions", "Recognition cycle", "Professional entry", "Employer acceptance"]
  },
  {
    key: "network",
    label: "Collaboration network and partner formation",
    keywords: [/network/i, /matching/i, /collaboration/i, /partner/i, /consortium/i, /网络/, /合作/, /撮合/, /伙伴/, /联合体/],
    packageIds: ["matching_platform", "project_supply", "market_access"],
    candidateKeys: ["project", "digital", "low_response", "pilot"],
    metrics: ["Qualified matches", "Joint bids", "Repeat partnerships", "Network density"]
  },
  {
    key: "regional",
    label: "Regional coverage and pilot scaling",
    keywords: [/regional/i, /pilot/i, /scale/i, /coverage/i, /spillover/i, /区域/, /试点/, /扩围/, /覆盖/, /溢出/],
    packageIds: ["market_access", "project_supply", "matching_platform"],
    candidateKeys: ["pilot", "project", "digital", "low_response"],
    metrics: ["Pilot conversion", "Regional reach", "Spillover", "Scale-up threshold"]
  },
  {
    key: "risk",
    label: "Implementation risk and outcome robustness",
    keywords: [/risk/i, /robust/i, /failure/i, /uncertainty/i, /weak/i, /constraint/i, /风险/, /稳健/, /失败/, /不确定/, /约束/],
    packageIds: ["approval", "market_access", "matching_platform"],
    candidateKeys: ["low_response", "approval_capacity", "pilot", "project"],
    metrics: ["Outcome robustness", "Adoption gap", "Unused capacity", "Implementation failure rate"]
  }
];

const policyDefaultResearchFocus = {
  "policy-hk-macao-coop": "participation",
  "policy-approval-fast-track": "efficiency",
  "policy-project-supply": "project",
  "policy-qualification-recognition": "qualification"
};

const policyScenarioProfiles = {
  "policy-approval-fast-track": {
    subject: "Approval facilitation",
    baselineName: "Current Approval Workflow",
    fullName: "GBA-Wide Approval Fast-Track",
    channelName: "Digital Application & Parallel Review",
    weakName: "Full Fast-Track, Weak Applicant Uptake",
    pilotName: "Selected-Project Approval Pilot",
    delivery: "Joint review desk and project approval teams",
    responseActor: "Applicants",
    pilotUnit: "selected eligible projects"
  },
  "policy-project-supply": {
    subject: "Cross-border project pipeline",
    baselineName: "Current Cross-Border Project Pipeline",
    fullName: "Full Cross-Border Project Pipeline",
    channelName: "Digital Project List & Partner Matching",
    weakName: "Full Project Supply, Weak Firm Response",
    pilotName: "Priority-Project Release Pilot",
    delivery: "Project owners, public agencies, and matching platform",
    responseActor: "Eligible firms",
    pilotUnit: "priority public-project batches"
  },
  "policy-qualification-recognition": {
    subject: "Professional qualification recognition",
    baselineName: "Current Qualification Recognition Practice",
    fullName: "GBA-Wide Qualification Recognition",
    channelName: "Digital Recognition Registry",
    weakName: "Full Recognition, Weak Employer Acceptance",
    pilotName: "Selected-Profession Recognition Pilot",
    delivery: "Recognition authority and professional registry",
    responseActor: "Professionals and employers",
    pilotUnit: "selected professional categories"
  }
};

function inferPolicyScenarioResearchFocus(objective, policy) {
  const fallbackKey = policyDefaultResearchFocus[policy?.id] || "participation";
  const fallback = policyScenarioResearchFocusDefinitions.find((item) => item.key === fallbackKey) || policyScenarioResearchFocusDefinitions[0];
  const objectiveText = String(objective || "").trim();
  if (!objectiveText || objectiveText === getPolicyExperimentQuestion(policy)) {
    return { ...fallback, secondaryKeys: [] };
  }

  const policyText = `${policy?.name || ""} ${policy?.summary || ""} ${policy?.rawText || ""}`;
  const ranked = policyScenarioResearchFocusDefinitions
    .map((focus, index) => {
      const objectiveHits = focus.keywords.reduce((total, keyword) => total + (keyword.test(objectiveText) ? 1 : 0), 0);
      const policyHits = focus.keywords.reduce((total, keyword) => total + (keyword.test(policyText) ? 1 : 0), 0);
      return {
        focus,
        score: objectiveHits * 12 + policyHits * 2 + (focus.key === fallbackKey ? 1 : 0),
        index
      };
    })
    .sort((a, b) => b.score - a.score || a.index - b.index);
  const selected = ranked[0]?.score > 0 ? ranked[0].focus : fallback;
  return {
    ...selected,
    secondaryKeys: ranked
      .filter((item) => item.focus.key !== selected.key && item.score >= 12)
      .slice(0, 2)
      .map((item) => item.focus.key)
  };
}

function uniqueScenarioValues(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function finalizePolicyExperimentBlueprints(blueprints, focus) {
  const scenarioIds = new Map(blueprints.map((item, index) => [item.key, `S${index}`]));
  return blueprints.map((blueprint, index) => {
    const id = `S${index}`;
    const comparisonIds = (blueprint.compareKeys || [])
      .map((key) => scenarioIds.get(key))
      .filter(Boolean);
    if (index > 0 && !comparisonIds.length) comparisonIds.push("S0");
    return {
      ...blueprint,
      id,
      scenarioId: blueprint.scenarioId || id,
      contrast: index === 0 ? "Reference" : `${id} vs ${comparisonIds.join(" / ")}`,
      primaryMetrics: uniqueScenarioValues([...(focus.metrics || []), ...(blueprint.primaryMetrics || [])]).slice(0, 4),
      generatedFocus: focus.label
    };
  });
}

function buildHkMacaoPolicyExperimentBlueprints(focus) {
  const fixed = policyExperimentBlueprints.filter((item) => ["baseline", "full"].includes(item.key));
  const optionalByKey = new Map(
    policyExperimentBlueprints
      .filter((item) => !["baseline", "full"].includes(item.key))
      .map((item) => [item.key, item])
  );
  const orderedKeys = uniqueScenarioValues([
    ...(focus.candidateKeys || []),
    ...policyExperimentBlueprints
      .filter((item) => !["baseline", "full"].includes(item.key))
      .sort((a, b) => {
        const aMatch = a.focusKeys?.includes(focus.key) ? 1 : 0;
        const bMatch = b.focusKeys?.includes(focus.key) ? 1 : 0;
        return bMatch - aMatch || (b.priority || 0) - (a.priority || 0);
      })
      .map((item) => item.key)
  ]);
  const selected = orderedKeys.map((key) => optionalByKey.get(key)).filter(Boolean).slice(0, 4);
  return finalizePolicyExperimentBlueprints([...fixed, ...selected], focus);
}

function buildGenericPolicyExperimentBlueprints(policy, focus) {
  const packages = getPolicyMechanismPackages(policy);
  const availableIds = packages.map((item) => item.id);
  const defaultIds = packages.filter((item) => item.defaultSelected).map((item) => item.id);
  const allIds = defaultIds.length ? defaultIds : availableIds;
  const focusIds = focus.packageIds.filter((packageId) => availableIds.includes(packageId));
  const primaryIds = focusIds.length ? focusIds : allIds.slice(0, 1);
  const supportingIds = uniqueScenarioValues([...primaryIds, ...allIds]).slice(0, Math.min(3, allIds.length));
  const channelIds = uniqueScenarioValues(
    ["approval", "matching_platform", "project_supply", "qualification", "market_access"].filter((packageId) => availableIds.includes(packageId))
  ).slice(0, Math.min(3, availableIds.length));
  const profile = policyScenarioProfiles[policy?.id] || {
    subject: policyUi(policy?.type || "Mapped policy"),
    baselineName: "Current Practice Baseline",
    fullName: `Comprehensive ${policyUi(policy?.type || "Policy")} Rollout`,
    channelName: "Targeted Digital Delivery Route",
    weakName: "Full Policy, Weak Target-Group Response",
    pilotName: "Phased Regional Pilot",
    delivery: "Responsible agencies and delivery partners",
    responseActor: "Target actors",
    pilotUnit: "selected regions and eligible cases"
  };
  const policyName = policyUi(policy?.name || "the mapped policy");
  const region = policyUi(policy?.region || "the target region");
  const packageLabel = (packageId) => policyUi(packages.find((item) => item.id === packageId)?.shortName || packageId);
  const strengths = (ids, primaryStrength = "medium", supportingStrength = primaryStrength) =>
    Object.fromEntries(uniqueScenarioValues(ids).map((packageId, index) => [packageId, index < primaryIds.length ? primaryStrength : supportingStrength]));
  const fullStrengths = Object.fromEntries(allIds.map((packageId) => [packageId, "medium"]));
  const focusNameByKey = {
    efficiency: "Approval-Capacity Matched Rollout",
    digital: "Digital Access Priority Route",
    participation: "Enterprise Uptake Support Route",
    project: "Project Opportunity-Led Rollout",
    qualification: "Qualification Recognition-First Rollout",
    network: "Partner Network-Led Rollout",
    regional: "Regional Scale-Up Route",
    risk: "Risk-Controlled Implementation Route"
  };
  const sharedMetrics = uniqueScenarioValues([
    ...focus.metrics,
    ...(policy?.expectedImpacts || []).map((item) => policyUi(item.label))
  ]).slice(0, 4);
  const fullPackageNames = allIds.map(packageLabel).join(", ");
  const focusPackageNames = supportingIds.map(packageLabel).join(", ");

  const blueprints = [
    {
      key: "baseline",
      name: profile.baselineName,
      type: "Reference",
      tone: "control",
      narrative: `${policyName} is not newly activated; current institutional and behavioral conditions continue in ${region}.`,
      hypothesis: "This run establishes the no-new-policy trajectory required to interpret every generated implementation pathway.",
      packageStrengths: {},
      coverage: `Current practice · ${region}`,
      deliveryMode: "Existing channels and institutional capacity",
      enterpriseResponse: "Observed baseline behavior",
      rolloutTiming: "No additional rollout",
      feedback: ["Current participation propensity", "Current delivery capacity", "No new policy reinforcement"],
      compareTo: "Common counterfactual",
      comparisonFocus: `Baseline trajectory for ${focus.label.toLowerCase()}`,
      resultReadout: `Establishes current performance before ${profile.subject.toLowerCase()} is introduced.`,
      decisionUse: "Use as the common counterfactual for every generated execution pathway.",
      primaryMetrics: sharedMetrics,
      guardrail: "Use the same agents, initial state, random seeds, simulation horizon, and metric definitions as every policy run.",
      compareKeys: []
    },
    {
      key: "full",
      name: profile.fullName,
      type: "Comprehensive rollout",
      tone: "integrated",
      narrative: `${policyName} is implemented as a coordinated package using ${fullPackageNames || "all mapped instruments"}.`,
      hypothesis: "Coordinating the complete policy package provides the highest credible implementation effect when institutions and target actors both respond.",
      packageStrengths: fullStrengths,
      coverage: `${region} · all eligible actors and cases`,
      deliveryMode: profile.delivery,
      enterpriseResponse: `High · ${profile.responseActor} actively respond`,
      rolloutTiming: "Full launch from Month 1",
      feedback: ["Delivery capacity adapts to demand", "Successful cases increase repeat participation", "Policy signals reinforce later decisions"],
      compareTo: "Full policy potential",
      comparisonFocus: `Maximum credible effect on ${focus.label.toLowerCase()}`,
      resultReadout: "Shows the attainable outcome when the complete package and target-group response are both present.",
      decisionUse: "Assess whether comprehensive rollout justifies its coordination and capacity requirements.",
      primaryMetrics: sharedMetrics,
      guardrail: "Track implementation capacity, concentration, and unresolved assumptions as the package scales.",
      compareKeys: ["baseline"]
    },
    {
      key: "focus",
      name: focusNameByKey[focus.key] || `${focus.label} Priority Route`,
      type: "Research-objective route",
      tone: "project",
      narrative: `${focusPackageNames || "The most relevant mapped instruments"} are prioritized to answer the stated research objective for ${policyName}.`,
      hypothesis: `Concentrating implementation on the instruments closest to ${focus.label.toLowerCase()} may retain most decision value with a smaller package.`,
      packageStrengths: strengths(supportingIds, "strong", "weak"),
      coverage: `${region} · actors directly linked to the research objective`,
      deliveryMode: `Focused delivery through ${focusPackageNames || profile.delivery}`,
      enterpriseResponse: `High among directly targeted ${profile.responseActor.toLowerCase()}`,
      rolloutTiming: "Priority route from Month 1",
      feedback: ["Targeted actors respond before the wider system", "Learning is concentrated in the selected pathway", "Complementary mechanisms remain limited"],
      compareTo: "Focused route versus full package",
      comparisonFocus: `Whether the research-priority route captures most of the ${focus.label.toLowerCase()} effect`,
      resultReadout: "Reveals whether a smaller, goal-aligned implementation route can outperform or approximate the full package.",
      decisionUse: "Choose this route when the research objective is more important than broad policy coverage.",
      primaryMetrics: sharedMetrics,
      guardrail: "Do not attribute omitted complementary effects to the selected route.",
      compareKeys: ["full", "baseline"]
    },
    {
      key: "channel",
      name: profile.channelName,
      type: "Alternative delivery model",
      tone: "digital",
      narrative: `${policyName} is delivered through a narrower channel using ${channelIds.map(packageLabel).join(", ") || "the available implementation tools"}.`,
      hypothesis: "A more standardized channel may improve reach and speed before the full institutional package is available.",
      packageStrengths: strengths(channelIds, "medium", "medium"),
      coverage: `${region} · digitally or administratively reachable cases`,
      deliveryMode: profile.channelName,
      enterpriseResponse: "High channel uptake · uneven offline reach",
      rolloutTiming: "Channel opens at Month 1",
      feedback: ["Channel use reinforces future adoption", "Offline actors respond more slowly", "Institutional constraints may remain outside the channel"],
      compareTo: "Delivery-channel trade-off",
      comparisonFocus: "Whether an alternative delivery model creates faster usable results",
      resultReadout: "Separates delivery-channel gains from the effect of comprehensive policy coverage.",
      decisionUse: "Use when a scalable channel is easier to implement than full institutional coordination.",
      primaryMetrics: sharedMetrics,
      guardrail: "Monitor exclusion, unresolved offline steps, and differences between formal access and completed participation.",
      compareKeys: ["focus", "baseline"]
    },
    {
      key: "low_response",
      name: profile.weakName,
      type: "Behavioral response risk",
      tone: "risk",
      narrative: `${policyName} is fully available, but ${profile.responseActor.toLowerCase()} remain cautious and use the new arrangements only occasionally.`,
      hypothesis: "Formal implementation can generate weak outcomes when awareness, trust, readiness, or complementary capability does not change.",
      packageStrengths: fullStrengths,
      coverage: "Same coverage as the comprehensive rollout",
      deliveryMode: profile.delivery,
      enterpriseResponse: `Low · 25% of eligible ${profile.responseActor.toLowerCase()} respond`,
      rolloutTiming: "Full launch from Month 1",
      feedback: ["Response propensity remains near baseline", "Successful cases create little repeat uptake", "Unused policy capacity accumulates"],
      compareTo: "Behavioral response penalty",
      comparisonFocus: `How much of the expected ${focus.label.toLowerCase()} effect depends on target-group response`,
      resultReadout: "Separates policy availability from actual adoption and downstream behavior.",
      decisionUse: "Determine whether outreach, trust building, incentives, or capability support are prerequisites for rollout.",
      primaryMetrics: sharedMetrics,
      guardrail: "Do not interpret low uptake as a design failure before awareness and readiness are checked.",
      compareKeys: ["full"]
    },
    {
      key: "pilot",
      name: profile.pilotName,
      type: "Phased pilot",
      tone: "pilot",
      narrative: `${policyName} begins with ${profile.pilotUnit} before expansion to the full ${region} scope.`,
      hypothesis: "A staged route can control implementation risk and produce evidence for scaling, although system-wide effects develop more slowly.",
      packageStrengths: Object.fromEntries(allIds.map((packageId) => [packageId, primaryIds.includes(packageId) ? "medium" : "weak"])),
      coverage: `${profile.pilotUnit} · limited initial coverage`,
      deliveryMode: "Phased eligibility and implementation batches",
      enterpriseResponse: "Moderate · invited actors respond first",
      rolloutTiming: "12-month pilot, then conditional expansion",
      feedback: ["Each batch updates delivery capacity", "Spillovers remain near pilot cases", "Expansion depends on conversion and capacity thresholds"],
      compareTo: "Scale versus controllability",
      comparisonFocus: `How much ${focus.label.toLowerCase()} benefit is retained under phased implementation`,
      resultReadout: "Shows the evidence available before scaling and the outcome sacrificed by limited early coverage.",
      decisionUse: "Use when uncertainty is high and decision-makers need an explicit scale-up gate.",
      primaryMetrics: sharedMetrics,
      guardrail: "Do not generalize pilot effects before differences in coverage and target composition are tested.",
      compareKeys: ["full", "baseline"]
    }
  ];
  return finalizePolicyExperimentBlueprints(blueprints, focus);
}

function buildPolicyExperimentBlueprints(policy, objective) {
  const focus = inferPolicyScenarioResearchFocus(objective, policy);
  if (policy?.id === "policy-hk-macao-coop") return buildHkMacaoPolicyExperimentBlueprints(focus);
  return buildGenericPolicyExperimentBlueprints(policy, focus);
}

const policyMappingCatalog = [
  {
    id: "policy-hk-macao-coop",
    name: "深化港澳合作若干措施",
    type: "港澳合作",
    project: "深化港澳合作政策仿真",
    region: "粤港澳大湾区",
    stageLabel: "情景待确认",
    stageTone: "review",
    version: "1.3",
    color: "orange",
    icon: Handshake,
    summary: "围绕规则衔接、重大项目参与、审批便利化、资质互认和合作撮合，量化港澳企业参与项目和跨区域合作网络变化。",
    rawText: "深化港澳合作，推动规则衔接和机制对接。鼓励港澳企业参与大湾区重大项目建设。对符合条件的项目实行绿色通道，审批时限压缩至10个工作日。",
    clauses: [
      { id: "C1", type: "宏观导向型", specificity: "0.22", path: "宏观变量路径", targets: "Contractor、Architect、QS、Supplier、Consultant", text: "深化港澳合作，推动规则衔接和机制对接。" },
      { id: "C2", type: "混合型", specificity: "0.48", path: "宏观变量 + 情景包路径", targets: "Owner、Contractor、Architect、QS、Supplier", text: "鼓励港澳企业参与大湾区重大项目建设。" },
      { id: "C3", type: "具体规则型", specificity: "0.81", path: "具体规则路径", targets: "Owner、Government", text: "对符合条件的项目实行绿色通道，审批时限压缩至10个工作日。" }
    ],
    mechanisms: [
      { name: "政策信号增强", target: "Contractor、Architect、QS、Supplier、Consultant", description: "提升港澳企业对大湾区项目机会的感知，增加进入市场和寻找伙伴的概率。" },
      { name: "跨区域阻力下降", target: "Contractor、Architect、QS、Supplier、Consultant", description: "通过规则衔接和机制对接降低跨境合作的不确定性和协作成本。" },
      { name: "审批便利化", target: "Owner、Government", description: "绿色通道和审批时限压缩直接降低项目等待时间，间接提高投标意愿。" },
      { name: "项目供给预期提升", target: "Owner、Contractor、Architect、QS", description: "重大项目参与机会增加，带动跨境合作项目发布和联合体组织。" }
    ],
    macroVariables: [
      { id: "policy_signal_strength", name: "政策信号强度", direction: "上升", delta: "+0.30", source: "宏观推断", confidence: "0.55", entry: "直接进入", entryTone: "ready" },
      { id: "market_openness_hk", name: "香港企业市场开放度", direction: "上升", delta: "+0.15", source: "宏观推断", confidence: "0.55", entry: "待审核", entryTone: "review" },
      { id: "partner_matching_efficiency", name: "合作撮合效率", direction: "上升", delta: "+0.15", source: "情景假设", confidence: "0.60", entry: "待审核", entryTone: "review" },
      { id: "cross_region_barrier", name: "跨区域合作阻力", direction: "下降", delta: "-0.15", source: "宏观推断", confidence: "0.55", entry: "直接进入", entryTone: "ready" }
    ],
    scenarios: [
      {
        id: "S0",
        name: "基准情景",
        strength: "No Policy",
        summary: "不引入新增政策工具，用于对照政策效果。",
        tools: ["基准"],
        assumptions: [
          { label: "审批时限", value: "维持20个工作日", source: "历史基准", tone: "history" },
          { label: "合作撮合", value: "成功率维持18%", source: "历史数据", tone: "history" }
        ]
      },
      {
        id: "S2",
        name: "弱实施情景",
        strength: "Low",
        summary: "政策信号增强，但具体配套工具有限，适合早期讨论。",
        tools: ["政策信号", "轻度撮合"],
        assumptions: [
          { label: "政策信号强度", value: "+0.18", source: "情景假设", tone: "assumption" },
          { label: "项目供给", value: "+12%", source: "系统推断", tone: "inference" }
        ]
      },
      {
        id: "S3",
        name: "中等实施情景",
        strength: "Medium",
        summary: "审批便利、项目供给、资质互认和合作撮合均有中等力度推进。",
        tools: ["审批便利", "项目供给", "资质互认", "合作撮合"],
        assumptions: [
          { label: "审批时限减少", value: "20个工作日 → 10个工作日", source: "政策明文 + 情景补足", tone: "explicit" },
          { label: "项目供给增加", value: "+30% 跨境合作项目", source: "情景假设", tone: "assumption" },
          { label: "合作撮合成功率", value: "提升至30%", source: "专家设定", tone: "expert" },
          { label: "资质互认范围", value: "新增5类专业", source: "专家设定", tone: "expert" }
        ]
      },
      {
        id: "S4",
        name: "强实施情景",
        strength: "High",
        summary: "强配套政策组合，检验政策上限和执行风险。",
        tools: ["强审批便利", "强项目供给", "平台撮合", "资金支持"],
        assumptions: [
          { label: "审批时限减少", value: "20个工作日 → 7个工作日", source: "情景假设", tone: "assumption" },
          { label: "跨境合作项目", value: "+45%", source: "专家设定", tone: "expert" }
        ]
      },
      {
        id: "S5",
        name: "审批便利单机制",
        strength: "Ablation",
        summary: "只开启审批便利，拆分审批机制对项目效率的贡献。",
        tools: ["审批便利"],
        assumptions: [
          { label: "绿色通道", value: "enabled", source: "政策明文", tone: "explicit" },
          { label: "材料数量", value: "12项 → 8项", source: "情景假设", tone: "assumption" }
        ]
      }
    ],
    atomicRules: [
      { id: "approval_deadline_days", name: "审批时限", before: "20", after: "10", unit: "工作日", source: "政策明文", confidence: "0.95", module: "项目审批", status: "已确认", statusTone: "ready" },
      { id: "green_channel_enabled", name: "绿色通道", before: "false", after: "true", unit: "", source: "政策明文", confidence: "0.90", module: "审批流程", status: "已确认", statusTone: "ready" },
      { id: "project_supply_growth_rate", name: "跨境项目供给增长率", before: "0", after: "0.30", unit: "", source: "情景假设", confidence: "0.58", module: "项目生成", status: "待审核", statusTone: "review" },
      { id: "partner_matching_success_rate", name: "撮合成功率", before: "0.18", after: "0.30", unit: "", source: "专家设定", confidence: "0.64", module: "合作网络", status: "待审核", statusTone: "review" },
      { id: "qualification_recognition_scope", name: "资质互认范围", before: "2", after: "5", unit: "类", source: "专家设定", confidence: "0.60", module: "企业准入", status: "待审核", statusTone: "review" }
    ],
    reviewItems: [
      { title: "审批时限压缩比例需要确认", detail: "中等情景采用10个工作日，强实施情景采用7个工作日，需合作方确认是否符合现实约束。", tone: "medium" },
      { title: "partner_matching_efficiency 来源为情景假设", detail: "当前由合作撮合平台设定推导，缺少历史撮合成功率校准。", tone: "medium" },
      { title: "项目供给增加比例敏感", detail: "project_supply_growth_rate 对港澳企业参与项目数影响较大，建议进入敏感性分析。", tone: "high" }
    ],
    versions: [
      { id: "v1.3", note: "新增中等实施情景和单机制审批消融", time: "2026-06-28" },
      { id: "v1.2", note: "补充资质互认和项目供给变量", time: "2026-06-27" },
      { id: "v1.0", note: "完成政策条款初始拆解", time: "2026-06-25" }
    ],
    expectedImpacts: [
      { label: "港澳企业参与项目数", width: "72%", delta: "+28%" },
      { label: "联合投标数量", width: "78%", delta: "+35%" },
      { label: "项目启动周期", width: "62%", delta: "-18%" },
      { label: "跨区域网络密度", width: "66%", delta: "+22%" }
    ],
    chain: [
      { label: "政策条款", value: "3条关键条款", icon: FileText },
      { label: "外部变化", value: "审批便利、项目供给、规则衔接", icon: Activity },
      { label: "变量 / 规则", value: "4个宏观变量 + 5个原子规则", icon: SlidersHorizontal },
      { label: "Agent行为", value: "参与、撮合、联合投标、项目启动", icon: Users },
      { label: "输出指标", value: "项目参与、效率、网络密度、风险", icon: BarChart3 }
    ]
  },
  {
    id: "policy-approval-fast-track",
    name: "港澳企业项目审批便利化细则",
    type: "审批细则",
    project: "深化港澳合作政策仿真",
    region: "深圳 / 横琴",
    stageLabel: "规则已生成",
    stageTone: "ready",
    version: "1.1",
    color: "blue",
    icon: FileCog,
    summary: "围绕绿色通道、线上申报和并联审批，直接量化项目审批周期、材料成本和项目启动效率。",
    rawText: "对符合条件的港澳企业参与项目开通绿色通道，审批时限压缩至7至10个工作日，支持线上申报和并联审批。",
    clauses: [
      { id: "C1", type: "具体规则型", specificity: "0.88", path: "具体规则路径", targets: "Owner、Government", text: "审批时限压缩至7至10个工作日。" },
      { id: "C2", type: "具体规则型", specificity: "0.84", path: "具体规则路径", targets: "Owner、Contractor、Architect、QS、Supplier", text: "支持线上申报和并联审批。" }
    ],
    mechanisms: [
      { name: "审批等待下降", target: "Owner、Government", description: "直接缩短审批等待时间，降低项目启动延迟。" },
      { name: "行政成本下降", target: "Contractor、Architect、QS、Supplier、Consultant", description: "线上申报减少材料准备和往返沟通成本。" }
    ],
    macroVariables: [
      { id: "approval_friction", name: "审批摩擦", direction: "下降", delta: "-0.40", source: "规则派生", confidence: "0.84", entry: "派生解释", entryTone: "draft" },
      { id: "participation_propensity_hk", name: "香港企业参与倾向", direction: "上升", delta: "+0.12", source: "机制推断", confidence: "0.62", entry: "待审核", entryTone: "review" }
    ],
    scenarios: [
      {
        id: "S1",
        name: "10日审批情景",
        strength: "Medium",
        summary: "审批时限压缩至10个工作日，启用线上申报。",
        tools: ["绿色通道", "线上申报"],
        assumptions: [
          { label: "审批时限", value: "20日 → 10日", source: "政策明文", tone: "explicit" },
          { label: "线上申报", value: "enabled", source: "政策明文", tone: "explicit" }
        ]
      },
      {
        id: "S2",
        name: "7日审批情景",
        strength: "High",
        summary: "审批时限压缩至7个工作日，并启用并联审批。",
        tools: ["绿色通道", "线上申报", "并联审批"],
        assumptions: [
          { label: "审批时限", value: "20日 → 7日", source: "政策明文", tone: "explicit" },
          { label: "并联审批", value: "enabled", source: "专家设定", tone: "expert" }
        ]
      }
    ],
    atomicRules: [
      { id: "approval_deadline_days", name: "审批时限", before: "20", after: "7", unit: "工作日", source: "政策明文", confidence: "0.95", module: "项目审批", status: "已确认", statusTone: "ready" },
      { id: "online_submission_enabled", name: "线上申报", before: "false", after: "true", unit: "", source: "政策明文", confidence: "0.88", module: "行政成本", status: "已确认", statusTone: "ready" },
      { id: "parallel_review_enabled", name: "并联审批", before: "false", after: "true", unit: "", source: "专家设定", confidence: "0.70", module: "审批流程", status: "待审核", statusTone: "review" }
    ],
    reviewItems: [
      { title: "并联审批是否同步实施", detail: "文本未明确所有项目均启用并联审批，需要确认适用范围。", tone: "medium" }
    ],
    versions: [
      { id: "v1.1", note: "补充并联审批参数", time: "2026-06-28" },
      { id: "v1.0", note: "完成审批时限和线上申报抽取", time: "2026-06-26" }
    ],
    expectedImpacts: [
      { label: "审批等待时间", width: "82%", delta: "-42%" },
      { label: "项目启动周期", width: "68%", delta: "-20%" },
      { label: "合作失败率", width: "28%", delta: "-3%" }
    ],
    chain: [
      { label: "政策条款", value: "2条审批规则", icon: FileText },
      { label: "外部变化", value: "审批时限和申报方式改变", icon: Activity },
      { label: "变量 / 规则", value: "3个原子规则", icon: SlidersHorizontal },
      { label: "Agent行为", value: "更快启动项目和投标准备", icon: Users },
      { label: "输出指标", value: "审批等待、启动周期、失败率", icon: BarChart3 }
    ]
  },
  {
    id: "policy-project-supply",
    name: "重点跨境合作项目清单",
    type: "项目清单",
    project: "跨境重大项目供给评估",
    region: "大湾区",
    stageLabel: "变量已生成",
    stageTone: "draft",
    version: "0.8",
    color: "green",
    icon: Building2,
    summary: "把新增项目清单转成项目供给、项目类型、允许港澳企业参与范围和联合体要求。",
    rawText: "发布重点跨境合作项目清单，鼓励港澳企业以联合体方式参与重大公共项目和创新合作项目。",
    clauses: [
      { id: "C1", type: "混合型", specificity: "0.52", path: "情景包路径", targets: "Owner、Government、Contractor", text: "发布重点跨境合作项目清单。" },
      { id: "C2", type: "混合型", specificity: "0.50", path: "情景包路径", targets: "Contractor、Architect、QS、Supplier、Consultant", text: "鼓励港澳企业以联合体方式参与重大公共项目。" }
    ],
    mechanisms: [
      { name: "项目供给增加", target: "Owner、Government", description: "新增清单提升跨境合作项目发布概率和项目规模。" },
      { name: "联合体机会增加", target: "Contractor、Architect、QS、Supplier、Consultant", description: "联合体要求提高跨区域合作边数量和重复合作机会。" }
    ],
    macroVariables: [
      { id: "cross_border_project_supply", name: "跨境项目供给", direction: "上升", delta: "+0.30", source: "情景假设", confidence: "0.50", entry: "待审核", entryTone: "review" },
      { id: "joint_bid_probability", name: "联合投标概率", direction: "上升", delta: "+0.18", source: "机制推断", confidence: "0.57", entry: "待审核", entryTone: "review" }
    ],
    scenarios: [
      {
        id: "S1",
        name: "清单发布情景",
        strength: "Medium",
        summary: "新增30%跨境合作项目，允许更多港澳企业参与。",
        tools: ["项目清单", "联合体"],
        assumptions: [
          { label: "项目供给", value: "+30%", source: "情景假设", tone: "assumption" },
          { label: "联合体比例", value: "+18%", source: "系统推断", tone: "inference" }
        ]
      }
    ],
    atomicRules: [
      { id: "project_supply_growth_rate", name: "项目供给增长率", before: "0", after: "0.30", unit: "", source: "情景假设", confidence: "0.50", module: "项目生成", status: "待审核", statusTone: "review" },
      { id: "joint_bid_required_share", name: "联合体项目占比", before: "0.12", after: "0.30", unit: "", source: "专家设定", confidence: "0.58", module: "投标机制", status: "待审核", statusTone: "review" }
    ],
    reviewItems: [
      { title: "项目清单缺少真实项目数量", detail: "当前以增长率模拟，需要导入真实项目清单后校准。", tone: "high" },
      { title: "联合体比例为专家设定", detail: "需确认清单中要求联合体参与的项目占比。", tone: "medium" }
    ],
    versions: [
      { id: "v0.8", note: "形成项目供给和联合体变量", time: "2026-06-28" }
    ],
    expectedImpacts: [
      { label: "跨境合作项目数量", width: "72%", delta: "+31%" },
      { label: "联合投标数量", width: "64%", delta: "+25%" },
      { label: "网络密度", width: "58%", delta: "+18%" }
    ],
    chain: [
      { label: "政策条款", value: "2条项目供给条款", icon: FileText },
      { label: "外部变化", value: "项目清单和联合体机会", icon: Activity },
      { label: "变量 / 规则", value: "2个宏观变量 + 2个规则", icon: SlidersHorizontal },
      { label: "Agent行为", value: "项目发布、联合投标、伙伴搜索", icon: Users },
      { label: "输出指标", value: "项目数量、投标数量、网络密度", icon: BarChart3 }
    ]
  },
  {
    id: "policy-qualification-recognition",
    name: "港澳专业资格互认办法",
    type: "资质规则",
    project: "跨境资质互认影响评估",
    region: "香港 / 澳门 / 内地",
    stageLabel: "待审核",
    stageTone: "review",
    version: "0.9",
    color: "brown",
    icon: Shield,
    summary: "量化资质互认范围、认定周期和准入限制变化，评估港澳专业服务企业参与机会。",
    rawText: "扩大港澳专业资格互认范围，缩短认定周期，支持符合条件的专业服务企业参与内地项目。",
    clauses: [
      { id: "C1", type: "混合型", specificity: "0.46", path: "情景包路径", targets: "Architect、QS、Consultant", text: "扩大港澳专业资格互认范围。" },
      { id: "C2", type: "具体规则型", specificity: "0.72", path: "具体规则路径", targets: "Architect、QS、Consultant", text: "缩短认定周期。" }
    ],
    mechanisms: [
      { name: "市场准入放宽", target: "Architect、QS、Consultant", description: "增加可参与项目的专业服务企业数量。" },
      { name: "资质转换成本下降", target: "Architect、QS、Consultant", description: "缩短认定周期，降低进入项目准备成本。" }
    ],
    macroVariables: [
      { id: "qualification_barrier", name: "资质壁垒", direction: "下降", delta: "-0.22", source: "宏观推断", confidence: "0.60", entry: "待审核", entryTone: "review" },
      { id: "professional_service_entry_rate", name: "专业服务企业进入率", direction: "上升", delta: "+0.16", source: "机制推断", confidence: "0.57", entry: "待审核", entryTone: "review" }
    ],
    scenarios: [
      {
        id: "S1",
        name: "中等互认情景",
        strength: "Medium",
        summary: "新增5类互认专业，认定周期缩短35%。",
        tools: ["资质互认", "周期缩短"],
        assumptions: [
          { label: "互认专业", value: "+5类", source: "专家设定", tone: "expert" },
          { label: "认定周期", value: "-35%", source: "情景假设", tone: "assumption" }
        ]
      }
    ],
    atomicRules: [
      { id: "qualification_recognition_scope", name: "互认专业范围", before: "2", after: "5", unit: "类", source: "专家设定", confidence: "0.60", module: "企业准入", status: "待审核", statusTone: "review" },
      { id: "recognition_cycle_reduction_rate", name: "认定周期压缩率", before: "0", after: "0.35", unit: "", source: "情景假设", confidence: "0.55", module: "准入流程", status: "待审核", statusTone: "review" }
    ],
    reviewItems: [
      { title: "互认范围缺少真实文件依据", detail: "需要补充互认专业清单或专家确认。", tone: "high" }
    ],
    versions: [
      { id: "v0.9", note: "形成资质壁垒和互认范围变量", time: "2026-06-27" }
    ],
    expectedImpacts: [
      { label: "专业服务企业参与率", width: "62%", delta: "+18%" },
      { label: "准入等待时间", width: "58%", delta: "-22%" },
      { label: "跨区域合作边", width: "49%", delta: "+12%" }
    ],
    chain: [
      { label: "政策条款", value: "2条资质规则", icon: FileText },
      { label: "外部变化", value: "资质互认和认定周期缩短", icon: Activity },
      { label: "变量 / 规则", value: "2个变量 + 2个规则", icon: SlidersHorizontal },
      { label: "Agent行为", value: "准入、参与项目、寻找伙伴", icon: Users },
      { label: "输出指标", value: "参与率、等待时间、合作边", icon: BarChart3 }
    ]
  }
];

const pageTitle = computed(() => ({
  overview: "Construction Simulation Overview",
  agent: "Construction Agent Library",
  policy: "Policy Mapping & External Change Quantification",
  workflow: "Simulation Workflow Configuration",
  simulation: "Greater Bay Area Construction Simulation",
  analytics: "Simulation Analytics",
  reports: "Simulation Reports",
  settings: "Platform Settings"
}[activeView.value]));

const pageSubtitle = computed(() => ({
  overview: "Monitor platform readiness, agent coverage, policy inputs, and simulation outputs in one workspace.",
  agent: "Build and inspect enterprise agents, clusters, capabilities, and collaboration readiness.",
  policy: "Manage policy text, target mechanisms, macro variables, implementation scenario packages, and atomic rule parameters for Agent simulation.",
  workflow: "Configure simulation phases, agent clusters, and policy interventions across the full workflow.",
  simulation: "Explore enterprise projects, partnerships, and regional collaboration through the full simulation timeline.",
  analytics: "Compare scenario outcomes, spatial distribution, collaboration networks, and policy effects.",
  reports: "Prepare concise exports for project timelines, agent engagement, metrics, and policy impact.",
  settings: "Manage platform defaults, model options, data sources, and simulation execution preferences."
}[activeView.value]));

const placeholderIcon = computed(() => ({
  overview: Building2,
  reports: FileText,
  settings: Settings
}[activeView.value] || Building2));

const placeholderCards = computed(() => {
  const cards = {
    overview: [
      { title: "Runtime Snapshot", text: "Backend status, active projects, and simulation readiness.", icon: LineChart },
      { title: "Agent Coverage", text: "Enterprise roles, regions, and collaboration availability.", icon: Users },
      { title: "Policy Inputs", text: "Scenario parameters mapped to simulation-ready controls.", icon: Shield },
      { title: "Network Health", text: "Cross-city collaboration and resource flow indicators.", icon: Network }
    ],
    reports: [
      { title: "Project Trace", text: "Stage transitions, performance history, and event logs.", icon: FileText },
      { title: "Agent Engagement", text: "Active, standby, released, and recalled participation records.", icon: Users },
      { title: "Policy Effect", text: "Approval efficiency, cost burden, and market participation.", icon: Shield },
      { title: "Export Pack", text: "Summary tables and visual evidence for scenario review.", icon: FolderDown }
    ],
    settings: [
      { title: "Simulation Defaults", text: "Tick duration, random seed, horizon, and output mode.", icon: Timer },
      { title: "Model Layer", text: "Rule-based execution first, optional CAMEL adapter later.", icon: Bot },
      { title: "Data Sources", text: "Agent catalogs, policies, clusters, and backend API endpoints.", icon: Database },
      { title: "Interface Density", text: "Readable cards, internal scroll, and dashboard-safe sizing.", icon: Settings }
    ]
  };
  return cards[activeView.value] || cards.overview;
});

const agentRows = computed(() => {
  const sourceAgents = backendAgents.value.length
    ? backendAgents.value.map(toAgentRow)
    : (simulationResult.value?.agent_results?.length ? simulationResult.value.agent_results : staticAgents);
  const agents = [...locallyCreatedAgents.value, ...sourceAgents];
  const keyword = agentKeyword.value.trim().toLowerCase();
  return agents.map((agent, index) => ({
    ...agent,
    rating: agent.rating || (4.1 + (index % 6) * 0.1).toFixed(1),
    projects: agent.projects || agent.project_count || 60 + index * 3,
    capabilities: [
      { label: "Financial Strength", value: capability(agent, "financial_capacity", 0.72) * 5 },
      { label: "Technical Capability", value: capability(agent, "technical_capability", 0.74) * 5 },
      { label: "Project Experience", value: capability(agent, "cross_region_experience", 0.70) * 5 },
      { label: "Innovation Level", value: capability(agent, "policy_adaptability", 0.68) * 5 },
      { label: "Compliance Level", value: capability(agent, "management_capability", 0.70) * 5 }
    ]
  })).filter((agent) => {
    const role = String(agent.role || "");
    const roleLabel = roleDisplayName(role);
    const matchesKeyword = !keyword || [agent.name, role, agent.region].some((value) =>
      String(value || "").toLowerCase().includes(keyword)
    );
    const matchesType =
      enterpriseTypeFilter.value === "All" ||
      (enterpriseTypeFilter.value === "Owner" && roleLabel === "Owner") ||
      (enterpriseTypeFilter.value === "Architect" && roleLabel === "Architect") ||
      (enterpriseTypeFilter.value === "Contractor" && roleLabel === "Contractor") ||
      (enterpriseTypeFilter.value === "Consultant" && ["QS", "Consultant"].includes(roleLabel)) ||
      (enterpriseTypeFilter.value === "Supplier" && roleLabel === "Supplier");
    const matchesRegion = enterpriseRegionFilter.value === "All Regions" || agent.region === enterpriseRegionFilter.value;
    return matchesKeyword && matchesType && matchesRegion;
  });
});
const displayAgentTotal = computed(() => {
  const backendTotal = agentTotal.value || (backendAgents.value.length ? backendAgents.value.length : 0);
  return backendTotal + locallyCreatedAgents.value.length || agentRows.value.length;
});
const agentTotalPages = computed(() => Math.max(1, Math.ceil((displayAgentTotal.value || 1) / agentPageSize.value)));
const agentPageStart = computed(() => {
  const total = displayAgentTotal.value;
  return total ? (agentPage.value - 1) * agentPageSize.value + 1 : 0;
});
const agentPageEnd = computed(() => Math.min(agentPage.value * agentPageSize.value, displayAgentTotal.value));

const selectedAgent = computed(() => {
  const profile = agentProfiles.value[selectedAgentId.value];
  if (profile) {
    const row = agentRows.value.find((agent) => agent.agent_id === selectedAgentId.value) || {};
    return { ...toAgentProfileUi(profile), rating: row.rating, projects: row.projects };
  }
  return agentRows.value.find((agent) => agent.agent_id === selectedAgentId.value) || agentRows.value[0] || staticAgents[0];
});
const selectedAgentCognitive = computed(() => agentCognitiveStates.value[selectedAgentId.value] || null);
const clusterRows = computed(() => backendClusters.value.length ? backendClusters.value.map(toClusterRow) : staticClusterRows);
const activeCluster = computed(() => clusterRows.value.find((cluster) => cluster.name === selectedCluster.value) || clusterRows.value[0]);
const selectedClusterDetail = computed(() => clusterDetails.value[activeCluster.value?.id]);
const policySourceRows = computed(() => {
  const rows = backendPolicies.value.length ? backendPolicies.value.map(toPolicyRow) : staticPolicyRows;
  return rows.map((policy) => ({ ...policy, icon: policy.icon || policyIcon(policy.type) }));
});
const policyTypeFilters = computed(() => {
  const availableTypes = [...new Set([...policyMappingCatalog, ...policySourceRows.value].map((policy) => policy.type).filter(Boolean))];
  const preferredTypes = ["All", "港澳合作", "审批细则", "项目清单", "资质规则", "Regulation", "Inter-regional", "Sustainability", "Technology", "Governance"];
  const orderedTypes = preferredTypes.filter((type) => type === "All" || availableTypes.includes(type));
  const extraTypes = availableTypes.filter((type) => !orderedTypes.includes(type));
  return [...orderedTypes, ...extraTypes].slice(0, 9);
});
const policyQuickTypeFilters = computed(() =>
  ["All", ...new Set(policyMappingCatalog.map((policy) => policy.type).filter(Boolean))].slice(0, 7)
);
const policyRegionOptions = computed(() => [
  "All Regions",
  ...new Set([...policyMappingCatalog, ...policySourceRows.value].map((policy) => policy.region).filter(Boolean))
]);
const policyHasActiveFilters = computed(() => policyTypeFilter.value !== "All" || policyRegionFilter.value !== "All Regions");
const policyRows = computed(() => {
  const keyword = policyKeyword.value.trim().toLowerCase();
  return policySourceRows.value.filter((policy) => {
    const matchesKeyword = !keyword || [policy.name, policy.type, policy.region, policy.status].some((value) =>
      String(value || "").toLowerCase().includes(keyword)
    );
    const matchesType = policyTypeFilter.value === "All" || policy.type === policyTypeFilter.value;
    const matchesRegion = policyRegionFilter.value === "All Regions" || policy.region === policyRegionFilter.value;
    return matchesKeyword && matchesType && matchesRegion;
  });
});
const activePolicy = computed(() =>
  policyRows.value.find((policy) => policy.name === selectedPolicy.value) ||
  policyRows.value[0] ||
  policySourceRows.value[0] ||
  staticPolicyRows[0]
);
const selectedPolicyDetail = computed(() => policyDetails.value[activePolicy.value?.id]);
const clusterComposition = computed(() => toClusterComposition(selectedClusterDetail.value));
const policyParams = computed(() => toPolicyParams(selectedPolicyDetail.value));
const policyImpacts = computed(() => toPolicyImpacts(policyPreview.value));
const policyMappingRows = computed(() => {
  const keyword = policyKeyword.value.trim().toLowerCase();
  return policyMappingCatalog.filter((policy) => {
    const matchesKeyword = !keyword || [
      policy.name,
      policy.type,
      policy.project,
      policy.region,
      policy.stageLabel,
      policy.summary
    ].some((value) => String(value || "").toLowerCase().includes(keyword));
    const matchesType = policyTypeFilter.value === "All" || policy.type === policyTypeFilter.value;
    const matchesRegion = policyRegionFilter.value === "All Regions" || policy.region === policyRegionFilter.value;
    return matchesKeyword && matchesType && matchesRegion;
  });
});
const policyMappingReviewPolicyTotal = computed(() =>
  policyMappingCatalog.filter((policy) => ["review", "draft"].includes(policy.stageTone)).length
);
const activeMappingPolicy = computed(() =>
  policyMappingRows.value.find((policy) => policy.id === selectedMappingPolicyId.value) ||
  policyMappingCatalog.find((policy) => policy.id === selectedMappingPolicyId.value) ||
  policyMappingRows.value[0] ||
  policyMappingCatalog[0]
);
const policyScenarioResearchFocus = computed(() =>
  inferPolicyScenarioResearchFocus(policyExperimentQuestionDraft.value, activeMappingPolicy.value) ||
  policyScenarioResearchFocusDefinitions[0] ||
  { key: "general", label: "Policy implementation", packageIds: [], candidateKeys: [], metrics: [] }
);
const policyExperimentQuestionExamples = computed(() =>
  getPolicyExperimentQuestionExamples(activeMappingPolicy.value)
);
const activeMappingSummaryChain = computed(() =>
  activeMappingPolicy.value.chain.filter((item) => !["外部变化", "Agent行为", "输出指标"].includes(item.label))
);
const activePolicySpecificityScore = computed(() => {
  const scores = activeMappingPolicy.value.clauses
    .map((clause) => Number(clause.specificity))
    .filter((score) => Number.isFinite(score));
  if (!scores.length) return "0.00";
  return (scores.reduce((sum, score) => sum + score, 0) / scores.length).toFixed(2);
});
const activePolicySpecificityLevel = computed(() => {
  const score = Number(activePolicySpecificityScore.value);
  if (score < 0.3) return "Use macro variables and optional mechanism packages.";
  if (score < 0.7) return "Use a two-layer model: macro variables plus implementation scenario packages.";
  return "Prioritize concrete rule parameters and retain macro signal variables.";
});

const splitPolicyRoles = (value) =>
  String(value || "")
    .split(/[、,，/]+/)
    .map((target) => target.trim())
    .filter(Boolean);

const activePolicyTargetRoles = computed(() => {
  const targets = activeMappingPolicy.value.clauses
    .flatMap((clause) => splitPolicyRoles(clause.targets));
  const uniqueTargets = [...new Set(targets)];
  return uniqueTargets.length ? uniqueTargets : ["To be identified"];
});

const activePolicyTargetSummary = computed(() =>
  activePolicyTargetRoles.value.length ? activePolicyTargetRoles.value.join(", ") : "To be identified"
);

const activePolicyGoalProfile = computed(() => {
  const text = activeMappingPolicy.value.rawText || "";
  if (/港澳|大湾区|规则衔接|机制对接/.test(text)) {
    return {
      primaryGoal: "Increase Hong Kong and Macao enterprise participation in Greater Bay Area development",
      categories: ["Regional Coordination", "Market Opening", "Project Collaboration"],
      description: "Improve cross-regional collaboration by connecting rules, project opportunities, cooperation mechanisms, and platform coordination."
    };
  }
  if (/审批|绿色通道|时限/.test(text)) {
    return {
      primaryGoal: "Reduce project approval friction and accelerate project launch",
      categories: ["Approval Optimization", "Administrative Efficiency"],
      description: "Improve project-start efficiency by simplifying approval paths, compressing timelines, and reducing administrative waiting cost."
    };
  }
  return {
    primaryGoal: "Translate macro policy intent into simulation-ready external changes",
    categories: ["Policy Quantification", "Scenario Design"],
    description: "Identify how the policy changes external conditions for agents before converting it into variables and rule parameters."
  };
});

const activePolicySubGoals = computed(() => [
  {
    title: "Easier Market Entry",
    description: "HK/Macao firms face lower barriers when entering mainland project markets.",
    icon: Globe2,
    tone: "tone-orange"
  },
  {
    title: "Better Rule Alignment",
    description: "Standards, qualifications, approval, and regulatory rules become more compatible.",
    icon: Shield,
    tone: "tone-slate"
  },
  {
    title: "More Project Opportunities",
    description: "More major projects become visible and accessible to HK/Macao participants.",
    icon: FolderOpen,
    tone: "tone-green"
  },
  {
    title: "Denser Cooperation Network",
    description: "Mainland and HK/Macao firms can form partnerships more easily.",
    icon: Network,
    tone: "tone-teal"
  },
  {
    title: "Smoother Resource Flow",
    description: "Capital, talent, data, and professional services move more smoothly across regions.",
    icon: Database,
    tone: "tone-amber"
  },
  {
    title: "Stronger Firm Expectations",
    description: "Firms become more confident that policy support will continue.",
    icon: TrendingUp,
    tone: "tone-blue"
  }
]);

const activePolicyTargetObjects = computed(() => {
  const roles = new Set(activePolicyTargetRoles.value);
  const objects = [
    {
      name: "Hong Kong / Macao Enterprises",
      role: "Direct beneficiaries",
      description: "Primary firms whose market entry, participation, and cooperation behavior may change.",
      icon: Building2,
      tone: "tone-orange",
      include: true
    },
    {
      name: "Mainland Project Owners",
      role: "Project providers",
      description: "Release project opportunities and define participation conditions.",
      icon: FolderOpen,
      tone: "tone-green",
      include: roles.has("Owner")
    },
    {
      name: "Mainland Enterprises",
      role: "Potential partners",
      description: "Form consortiums, bids, and cooperation links with HK/Macao firms.",
      icon: Users,
      tone: "tone-teal",
      include: roles.has("Contractor") || roles.has("Supplier")
    },
    {
      name: "Government / Platform Agent",
      role: "Coordinator and regulator",
      description: "Supports approval, matching, resource allocation, and policy execution.",
      icon: Shield,
      tone: "tone-blue",
      include: roles.has("Government")
    },
    {
      name: "Professional Service Providers",
      role: "Specialized participants",
      description: "Architects, QS, consultants, and related professionals affected by qualification rules.",
      icon: DraftingCompass,
      tone: "tone-violet",
      include: roles.has("Architect") || roles.has("QS") || roles.has("Consultant")
    }
  ];
  return objects.filter((object) => object.include);
});

const activePolicyActionDomains = computed(() => [
  {
    name: "Market Access",
    description: "Whether firms can enter and how high the entry threshold is.",
    effect: "Changes eligibility and participation probability",
    icon: Globe2,
    tone: "tone-orange"
  },
  {
    name: "Approval Process",
    description: "Whether approval is faster, simpler, and less costly.",
    effect: "Changes waiting cost and project-start cycle",
    icon: FileCog,
    tone: "tone-blue"
  },
  {
    name: "Qualification Recognition",
    description: "Whether HK/Macao qualifications are recognized for mainland participation.",
    effect: "Changes professional entry and compliance barrier",
    icon: Shield,
    tone: "tone-violet"
  },
  {
    name: "Project Supply",
    description: "Whether there are more open projects for HK/Macao participation.",
    effect: "Changes project opportunity pool",
    icon: FolderOpen,
    tone: "tone-green"
  },
  {
    name: "Partner Matching",
    description: "Whether firms can find suitable cross-regional partners more easily.",
    effect: "Changes network formation and joint-bid probability",
    icon: Network,
    tone: "tone-teal"
  },
  {
    name: "Policy Signal",
    description: "Whether the policy strengthens enterprise confidence and expectations.",
    effect: "Changes participation expectation and strategic response",
    icon: TrendingUp,
    tone: "tone-amber"
  }
]);

const policyInstrumentLabel = (item) => {
  const text = `${item?.id || ""} ${item?.name || ""} ${item?.mechanism || ""}`;
  if (/market|准入|开放/.test(text)) return "Access Relaxation";
  if (/approval|审批/.test(text)) return "Approval Optimization";
  if (/qualification|资质|recognition/.test(text)) return "Qualification Recognition";
  if (/project|项目|supply/.test(text)) return "Project Opening";
  if (/matching|撮合|platform/.test(text)) return "Platform Matching";
  if (/funding|融资|资金/.test(text)) return "Fiscal / Financial Support";
  return "Policy Instrument";
};

const mechanismRelatedSubGoals = (item) => {
  const map = {
    market_access: ["Easier Market Entry", "Stronger Firm Expectations"],
    approval: ["More Project Opportunities", "Stronger Firm Expectations"],
    qualification: ["Better Rule Alignment", "Smoother Resource Flow"],
    project_supply: ["More Project Opportunities", "Denser Cooperation Network"],
    matching_platform: ["Denser Cooperation Network", "Easier Market Entry"],
    funding: ["Smoother Resource Flow", "Stronger Firm Expectations"]
  };
  return map[item?.id] || ["Stronger Firm Expectations"];
};

const mechanismRelatedTargetObjects = (item) => {
  const map = {
    market_access: ["Hong Kong / Macao Enterprises", "Government / Platform Agent"],
    approval: ["Mainland Project Owners", "Government / Platform Agent", "Hong Kong / Macao Enterprises"],
    qualification: ["Professional Service Providers", "Hong Kong / Macao Enterprises"],
    project_supply: ["Mainland Project Owners", "Hong Kong / Macao Enterprises", "Mainland Enterprises"],
    matching_platform: ["Hong Kong / Macao Enterprises", "Mainland Enterprises", "Government / Platform Agent"],
    funding: ["Hong Kong / Macao Enterprises", "Financial Institutions"]
  };
  return map[item?.id] || ["Hong Kong / Macao Enterprises"];
};

const mechanismRelatedActionDomains = (item) => {
  const map = {
    market_access: ["Market Access", "Policy Signal"],
    approval: ["Approval Process", "Policy Signal"],
    qualification: ["Qualification Recognition", "Standard Rules"],
    project_supply: ["Project Supply", "Partner Matching"],
    matching_platform: ["Partner Matching", "Project Supply"],
    funding: ["Financing", "Project Supply"]
  };
  return map[item?.id] || ["Policy Signal"];
};

const activePolicyTextTriggers = computed(() => {
  const text = activeMappingPolicy.value.rawText || "";
  const triggers = [];
  if (/规则衔接/.test(text)) triggers.push("rule alignment");
  if (/机制对接/.test(text)) triggers.push("mechanism alignment");
  if (/重大项目/.test(text)) triggers.push("major projects");
  if (/绿色通道/.test(text)) triggers.push("green channel");
  if (/审批/.test(text)) triggers.push("approval deadline");
  if (/资质|互认/.test(text)) triggers.push("qualification recognition");
  if (/撮合|伙伴|联合体/.test(text)) triggers.push("partner matching");
  return triggers.length ? triggers : ["macro policy signal"];
});

const mechanismTone = (item) => {
  const text = `${item?.id || ""} ${item?.name || ""} ${item?.mechanism || ""}`.toLowerCase();
  if (/approval|审批/.test(text)) return "tone-blue";
  if (/project|项目|supply/.test(text)) return "tone-green";
  if (/qualification|资质|recognition/.test(text)) return "tone-violet";
  if (/matching|撮合|partner/.test(text)) return "tone-teal";
  if (/funding|融资|资金/.test(text)) return "tone-amber";
  if (/barrier|阻力/.test(text)) return "tone-slate";
  return "tone-orange";
};

const mechanismCategoryLabel = (mechanism) => {
  const text = `${mechanism?.name || ""} ${mechanism?.description || ""}`;
  if (/信号|awareness|signal/i.test(text)) return "Policy signal";
  if (/审批|green|deadline/i.test(text)) return "Process efficiency";
  if (/项目|supply|opportunit/i.test(text)) return "Project opportunity";
  if (/阻力|cost|uncertainty/i.test(text)) return "Coordination cost";
  return "Behavior environment";
};

const mechanismTargetRoles = (mechanism) => {
  const roles = splitPolicyRoles(mechanism?.target);
  return roles.length ? roles : ["To be identified"];
};

const mechanismPathLabel = (mechanism) => {
  const text = `${mechanism?.name || ""} ${mechanism?.description || ""}`;
  if (/信号|awareness|signal/i.test(text)) return "market entry / partner search";
  if (/审批|green|deadline/i.test(text)) return "waiting cost / bid willingness";
  if (/项目|supply|opportunit/i.test(text)) return "project release / consortium formation";
  if (/阻力|cost|uncertainty/i.test(text)) return "coordination cost / collaboration probability";
  return "agent behavior environment";
};

const policySpecificityDimensions = computed(() => {
  const text = activeMappingPolicy.value.rawText || "";
  const hasNumber = /\d/.test(text);
  const hasRule = /(审批|绿色通道|线上|并联|互认|清单|压缩|支持|鼓励)/.test(text);
  return [
    { label: "Numeric Target", value: hasNumber ? "0.72" : "0.25" },
    { label: "Rule Clarity", value: hasRule ? "0.68" : "0.32" },
    { label: "Target Clarity", value: /(港澳企业|项目|专业服务|企业)/.test(text) ? "0.76" : "0.45" },
    { label: "Time Clarity", value: /(日|月|年|周期|阶段)/.test(text) ? "0.58" : "0.24" },
    { label: "Resource Clarity", value: /(资金|项目|清单|平台|数据|人才)/.test(text) ? "0.61" : "0.30" }
  ];
});

const policyProcessStageGroups = [
  { id: "access", label: "ACCESS", description: "Opportunity and eligibility" },
  { id: "decision", label: "DECISION", description: "Application and approval" },
  { id: "formation", label: "FORMATION", description: "Matching and commitment" },
  { id: "delivery", label: "DELIVERY", description: "Execution and assurance" }
];

const policyProcessStages = [
  { id: "discover", label: "Opportunity Discovery", shortLabel: "Discover", description: "Signal & project visibility" },
  { id: "qualify", label: "Entry Qualification", shortLabel: "Qualify", description: "Eligibility & rights" },
  { id: "apply", label: "Application", shortLabel: "Apply", description: "Submission & materials" },
  { id: "review", label: "Review & Approval", shortLabel: "Review", description: "Decision & timeline" },
  { id: "match", label: "Matching & Tender", shortLabel: "Match", description: "Partner & bid" },
  { id: "contract", label: "Contract & Start", shortLabel: "Start", description: "Award & commitment" },
  { id: "deliver", label: "Project Delivery", shortLabel: "Deliver", description: "Execution & resources" },
  { id: "comply", label: "Oversight & Compliance", shortLabel: "Comply", description: "Monitoring & control" }
];

const policyInterventionModules = [
  {
    id: "market_entry",
    label: "Market Entry Enablement",
    description: "Make participation legally and operationally possible.",
    expectedChange: "More Hong Kong and Macao firms become eligible and can enter the application process with less administrative friction.",
    stageStart: "qualify",
    stageEnd: "review",
    tone: "tone-indigo",
    icon: Globe2,
    rowHeight: 350
  },
  {
    id: "opportunity_activation",
    label: "Project Opportunity Activation",
    description: "Create visible and accessible project opportunities.",
    expectedChange: "Firms can identify a larger and more predictable pool of cross-border projects that are open for participation.",
    stageStart: "discover",
    stageEnd: "match",
    tone: "tone-gold",
    icon: FolderOpen,
    rowHeight: 170
  },
  {
    id: "partnership_formation",
    label: "Partnership Formation",
    description: "Help firms find partners and form delivery structures.",
    expectedChange: "Compatible firms find one another faster and convert qualified matches into joint bids and delivery partnerships.",
    stageStart: "match",
    stageEnd: "contract",
    tone: "tone-teal",
    icon: Network,
    rowHeight: 140
  },
  {
    id: "resource_support",
    label: "Resource & Incentive Support",
    description: "Improve the economics and capacity of participation.",
    expectedChange: "Targeted support improves expected project returns and strengthens firms' capacity to commit and deliver.",
    stageStart: "contract",
    stageEnd: "deliver",
    tone: "tone-green",
    icon: Database,
    rowHeight: 130
  },
  {
    id: "governance",
    label: "Governance & Risk Safeguard",
    description: "Control compliance, delivery, and implementation risk.",
    expectedChange: "Delivery and compliance risks should be monitored and constrained, but no direct safeguard instrument is currently specified.",
    stageStart: "deliver",
    stageEnd: "comply",
    tone: "tone-violet",
    icon: Shield,
    rowHeight: 110
  }
];

const policyInterventionTypeLegend = [
  { id: "rules", label: "Rules & Rights", shortLabel: "Rules", tone: "tone-indigo" },
  { id: "process", label: "Process & Services", shortLabel: "Process", tone: "tone-blue" },
  { id: "information", label: "Information & Coordination", shortLabel: "Coordination", tone: "tone-teal" },
  { id: "incentives", label: "Incentives & Resources", shortLabel: "Resources", tone: "tone-green" },
  { id: "supply", label: "Supply & Capacity", shortLabel: "Supply", tone: "tone-gold" },
  { id: "oversight", label: "Oversight & Risk", shortLabel: "Oversight", tone: "tone-violet" }
];

const policyAtomicInstrumentMetadata = {
  eligible_project_ratio_hk_macao: {
    instrument: "Eligible Project Scope",
    familyId: "rules",
    family: "Rules & Rights",
    tone: "tone-indigo",
    icon: Globe2,
    module: "market_entry",
    stage: "qualify",
    clausePattern: /港澳企业参与|参与大湾区重大项目/,
    mechanism: "Expands the share of projects for which Hong Kong and Macao firms are legally eligible.",
    agentResponse: "More eligible firms consider entry and submit for suitable projects.",
    outcome: "Higher enterprise participation and broader cross-regional market access."
  },
  market_entry_review_required: {
    instrument: "Pre-entry Review Rule",
    familyId: "rules",
    family: "Rules & Rights",
    tone: "tone-indigo",
    icon: Shield,
    module: "market_entry",
    stage: "qualify",
    clausePattern: /港澳企业参与|规则衔接/,
    mechanism: "Removes a pre-entry review gate that otherwise delays access to the project market.",
    agentResponse: "Eligible firms can enter the application process without an additional screening step.",
    outcome: "Lower entry friction and a larger effective applicant pool."
  },
  recognized_profession_count: {
    instrument: "Qualification Recognition Scope",
    familyId: "rules",
    family: "Rules & Rights",
    tone: "tone-indigo",
    icon: Shield,
    module: "market_entry",
    stage: "qualify",
    clausePattern: /规则衔接|机制对接|资质|互认/,
    mechanism: "Expands the set of professional qualifications recognized across regions.",
    agentResponse: "More firms and professionals become eligible without duplicative accreditation.",
    outcome: "A larger qualified participant pool and smoother professional-service mobility."
  },
  recognition_processing_days: {
    instrument: "Recognition Processing Limit",
    familyId: "process",
    family: "Process & Services",
    tone: "tone-blue",
    icon: Workflow,
    module: "market_entry",
    stage: "review",
    clausePattern: /规则衔接|机制对接|资质|互认/,
    mechanism: "Sets a shorter administrative cycle for cross-regional qualification recognition.",
    agentResponse: "Professionals become operationally available earlier in the project cycle.",
    outcome: "Faster professional entry and lower compliance waiting cost."
  },
  online_submission_enabled: {
    instrument: "Online Submission",
    familyId: "process",
    family: "Process & Services",
    tone: "tone-blue",
    icon: FileCog,
    module: "market_entry",
    stage: "apply",
    clausePattern: /审批|绿色通道|申报/,
    mechanism: "Reduces document-delivery cost and allows firms to complete applications remotely.",
    agentResponse: "Firms submit more complete applications with less administrative effort.",
    outcome: "Higher application completion and lower transaction cost."
  },
  required_material_count: {
    instrument: "Required Material Reduction",
    familyId: "process",
    family: "Process & Services",
    tone: "tone-blue",
    icon: FileText,
    module: "market_entry",
    stage: "apply",
    clausePattern: /审批|绿色通道|申报/,
    mechanism: "Reduces the documentary burden needed to enter the approval process.",
    agentResponse: "More eligible firms complete submissions without abandonment or correction cycles.",
    outcome: "Lower application friction and faster review readiness."
  },
  green_channel_enabled: {
    instrument: "Green Channel",
    familyId: "process",
    family: "Process & Services",
    secondaryFamily: "Coordination",
    tone: "tone-blue",
    icon: Workflow,
    module: "market_entry",
    stage: "review",
    clausePattern: /绿色通道|审批/,
    mechanism: "Prioritizes eligible projects and coordinates review steps through an accelerated route.",
    agentResponse: "Firms complete applications faster and project owners start qualified projects earlier.",
    outcome: "Shorter project-start cycles and higher conversion from interest to participation."
  },
  parallel_review_enabled: {
    instrument: "Parallel Review",
    familyId: "process",
    family: "Process & Services",
    secondaryFamily: "Coordination",
    tone: "tone-blue",
    icon: Workflow,
    module: "market_entry",
    stage: "review",
    clausePattern: /审批|绿色通道/,
    mechanism: "Allows multiple review activities to proceed concurrently instead of sequentially.",
    agentResponse: "Project owners and applicants receive a final decision with fewer inter-agency delays.",
    outcome: "Shorter approval cycles and reduced implementation uncertainty."
  },
  approval_deadline_days: {
    instrument: "Approval Deadline Cap",
    familyId: "process",
    family: "Process & Services",
    tone: "tone-blue",
    icon: Timer,
    module: "market_entry",
    stage: "review",
    clausePattern: /审批时限|工作日|绿色通道/,
    mechanism: "Caps the maximum approval duration and lowers uncertainty about project-start timing.",
    agentResponse: "Firms face lower waiting costs and project owners commit earlier.",
    outcome: "Faster project starts and higher conversion from approved opportunity to delivery."
  },
  project_supply_growth_rate: {
    instrument: "Cross-border Project Supply",
    familyId: "supply",
    family: "Supply & Capacity",
    tone: "tone-gold",
    icon: FolderOpen,
    module: "opportunity_activation",
    stage: "discover",
    clausePattern: /重大项目|项目建设|项目/,
    mechanism: "Makes a larger and more predictable pool of cross-border projects visible to firms.",
    agentResponse: "Firms identify more relevant opportunities and invest more effort in project pursuit.",
    outcome: "More viable project opportunities and a stronger participation pipeline."
  },
  key_project_list_enabled: {
    instrument: "Priority Project List",
    familyId: "supply",
    family: "Supply & Capacity",
    secondaryFamily: "Information",
    tone: "tone-gold",
    icon: FolderOpen,
    module: "opportunity_activation",
    stage: "discover",
    clausePattern: /重大项目|项目建设|项目/,
    mechanism: "Publishes a structured list of priority projects and their participation conditions.",
    agentResponse: "Firms discover suitable opportunities earlier and allocate pursuit resources more precisely.",
    outcome: "Higher opportunity visibility and a more predictable participation pipeline."
  },
  partner_matching_success_rate: {
    instrument: "Partner Matching Service",
    familyId: "information",
    family: "Information & Coordination",
    tone: "tone-teal",
    icon: Network,
    module: "partnership_formation",
    stage: "match",
    clausePattern: /深化港澳合作|机制对接|合作/,
    mechanism: "Reduces partner-search friction and improves compatibility information between firms.",
    agentResponse: "Mainland and Hong Kong / Macao firms form consortiums and joint bids more often.",
    outcome: "Denser collaboration networks and a higher cross-regional matching success rate."
  },
  platform_broker_power: {
    instrument: "Active Platform Brokerage",
    familyId: "information",
    family: "Information & Coordination",
    tone: "tone-teal",
    icon: Network,
    module: "partnership_formation",
    stage: "match",
    clausePattern: /深化港澳合作|机制对接|合作/,
    mechanism: "Allows the platform agent to actively recommend compatible partners and coordinate introductions.",
    agentResponse: "Firms receive higher-quality partner options and form viable collaboration structures faster.",
    outcome: "Higher matching conversion and stronger network connectivity."
  },
  joint_bid_recommendation_enabled: {
    instrument: "Joint-bid Recommendation",
    familyId: "information",
    family: "Information & Coordination",
    secondaryFamily: "Process",
    tone: "tone-teal",
    icon: Handshake,
    module: "partnership_formation",
    stage: "contract",
    clausePattern: /深化港澳合作|机制对接|重大项目/,
    mechanism: "Recommends consortium structures that satisfy project capability and eligibility requirements.",
    agentResponse: "Matched firms convert relationships into joint bids and contractual commitments.",
    outcome: "More cross-regional consortiums and a higher bid-participation rate."
  },
  subsidy_rate: {
    instrument: "Participation Subsidy",
    familyId: "incentives",
    family: "Incentives & Resources",
    tone: "tone-green",
    icon: Database,
    module: "resource_support",
    stage: "contract",
    clausePattern: /支持|重大项目|项目/,
    mechanism: "Improves expected project returns and reduces financing constraints during implementation.",
    agentResponse: "Firms accept more viable matches and maintain delivery capacity after award.",
    outcome: "Stronger project conversion, resource flow, and delivery continuity."
  }
};

const policyInstrumentRelationDefinitions = [
  {
    source: "key_project_list_enabled",
    target: "eligible_project_ratio_hk_macao",
    type: "Precedes",
    condition: "Applies to projects opened to Hong Kong and Macao enterprises."
  },
  {
    source: "eligible_project_ratio_hk_macao",
    target: "online_submission_enabled",
    type: "Requires",
    condition: "Only eligible firms proceed to application."
  },
  {
    source: "recognized_profession_count",
    target: "green_channel_enabled",
    type: "Complements",
    condition: "Relevant to recognized professional-service applicants."
  },
  {
    source: "online_submission_enabled",
    target: "approval_deadline_days",
    type: "Complements",
    condition: "Digital submission supports the shortened review cycle."
  },
  {
    source: "required_material_count",
    target: "approval_deadline_days",
    type: "Amplifies",
    condition: "Active only in the strong implementation scenario."
  },
  {
    source: "green_channel_enabled",
    target: "partner_matching_success_rate",
    type: "Precedes",
    condition: "Approved projects proceed to partner formation."
  },
  {
    source: "approval_deadline_days",
    target: "partner_matching_success_rate",
    type: "Precedes",
    condition: "A predictable decision window improves matching conversion."
  },
  {
    source: "project_supply_growth_rate",
    target: "partner_matching_success_rate",
    type: "Amplifies",
    condition: "A larger opportunity pool increases viable matching options."
  },
  {
    source: "partner_matching_success_rate",
    target: "joint_bid_recommendation_enabled",
    type: "Complements",
    condition: "Recommended joint bids are generated after a viable match."
  },
  {
    source: "subsidy_rate",
    target: "joint_bid_recommendation_enabled",
    type: "Amplifies",
    condition: "Enabled only when the funding-support package is included."
  }
];

const activeMechanismPackages = computed(() => {
  const packageIds = policyImplementationPackageMap[activeMappingPolicy.value?.id] || defaultImplementationPackages.map((item) => item.id);
  return packageIds
    .map((packageId) => defaultImplementationPackages.find((item) => item.id === packageId))
    .filter(Boolean);
});

const activePolicyInterventionNodes = computed(() =>
  activeMechanismPackages.value.flatMap((item) => {
    const rules = getMechanismPackageLevel(item)?.rules || [];
    return rules.map((rule) => {
      const customRule = customAtomicRuleDraft.value[rule.id];
      const effectiveRule = customRule
        ? {
            ...rule,
            after: customRule.after,
            customized: true
          }
        : rule;
      const architecture = policyAtomicInstrumentMetadata[rule.id] || {
        instrument: policyUi(rule.name),
        familyId: "oversight",
        family: "Oversight & Risk",
        tone: "tone-violet",
        icon: Shield,
        module: "governance",
        stage: "comply",
        clausePattern: /./,
        mechanism: policyUi(item.mechanism),
        agentResponse: "Affected agents adjust their behavior in response to the changed external condition.",
        outcome: mechanismRelatedSubGoals(item)[0] || "Improved policy outcome"
      };
      const clauses = activeMappingPolicy.value?.clauses || [];
      const evidenceClause =
        clauses.find((clause) => architecture.clausePattern?.test(clause.text || "")) ||
        clauses[0] ||
        null;
      return {
        ...architecture,
        id: rule.id,
        packageId: item.id,
        item,
        rule: effectiveRule,
        baseRule: rule,
        familyShort:
          policyInterventionTypeLegend.find((type) => type.id === architecture.familyId)?.shortLabel ||
          architecture.family,
        clauseId: evidenceClause?.id || "Derived",
        evidenceClause,
        selected: selectedAtomicInstrumentIds.value.includes(rule.id)
      };
    });
  })
);

const selectedPolicyAtomicInstruments = computed(() =>
  activePolicyInterventionNodes.value.filter((node) => node.selected)
);

const activePolicyInterventionModules = computed(() =>
  policyInterventionModules.map((module, index) => {
    const nodes = activePolicyInterventionNodes.value.filter((node) => node.module === module.id);
    const instrumentCount = nodes.length;
    const startIndex = Math.max(0, policyProcessStages.findIndex((stage) => stage.id === module.stageStart));
    const endIndex = Math.max(startIndex, policyProcessStages.findIndex((stage) => stage.id === module.stageEnd));
    const evidenceCount = new Set(nodes.map((node) => node.clauseId).filter(Boolean)).size;
    return {
      ...module,
      index: String(index + 1).padStart(2, "0"),
      instrumentCount,
      selectedCount: nodes.filter((node) => node.selected).length,
      evidenceCount,
      typeCount: new Set(nodes.map((node) => node.familyId)).size,
      startIndex,
      endIndex,
      stageSpan: endIndex - startIndex + 1,
      stageRange: `${policyProcessStages[startIndex]?.label || ""} → ${policyProcessStages[endIndex]?.label || ""}`,
      gap: instrumentCount === 0
    };
  })
);

const activePolicyModuleCount = computed(() =>
  activePolicyInterventionModules.value.filter((module) => !module.gap).length
);

const activePolicyRelations = computed(() => {
  const nodesById = new Map(activePolicyInterventionNodes.value.map((node) => [node.id, node]));
  return policyInstrumentRelationDefinitions
    .filter((relation) => nodesById.has(relation.source) && nodesById.has(relation.target))
    .map((relation) => ({
      ...relation,
      sourceLabel: nodesById.get(relation.source).instrument,
      targetLabel: nodesById.get(relation.target).instrument
    }));
});

const activePolicyTypeCount = computed(() =>
  new Set(activePolicyInterventionNodes.value.map((node) => node.familyId)).size
);

const activePolicyStageCount = computed(() =>
  new Set(activePolicyInterventionNodes.value.map((node) => node.stage)).size
);

const selectedPolicyModule = computed(() =>
  activePolicyInterventionModules.value.find((module) => module.id === expandedPolicyModuleId.value) || null
);

const expandedPolicyModuleNodes = computed(() =>
  selectedPolicyModule.value
    ? activePolicyInterventionNodes.value.filter((node) => node.module === selectedPolicyModule.value.id)
    : []
);

const expandedPolicyModuleRelations = computed(() => {
  const moduleNodeIds = new Set(expandedPolicyModuleNodes.value.map((node) => node.id));
  return activePolicyRelations.value.filter(
    (relation) => moduleNodeIds.has(relation.source) || moduleNodeIds.has(relation.target)
  );
});

const expandedPolicyModuleInternalRelations = computed(() => {
  const moduleNodeIds = new Set(expandedPolicyModuleNodes.value.map((node) => node.id));
  return expandedPolicyModuleRelations.value.filter(
    (relation) => moduleNodeIds.has(relation.source) && moduleNodeIds.has(relation.target)
  );
});

const selectedPolicyInterventionNode = computed(() =>
  expandedPolicyModuleNodes.value.find((node) => node.id === selectedPolicyInstrumentId.value) ||
  expandedPolicyModuleNodes.value[0] ||
  null
);

const selectedPolicyRuleNarrative = computed(() => {
  const node = selectedPolicyInterventionNode.value;
  if (!node) return "";
  return [node.mechanism, node.agentResponse]
    .filter(Boolean)
    .map((sentence) => String(sentence).trim())
    .join(" ");
});

const selectedPolicyRuleIsCustom = computed(() => {
  const ruleId = selectedPolicyInterventionNode.value?.id;
  return Boolean(ruleId && Object.prototype.hasOwnProperty.call(customAtomicRuleDraft.value, ruleId));
});

const selectedPolicyCustomInputConfig = computed(() =>
  getAtomicRuleInputConfig(selectedPolicyInterventionNode.value?.baseRule || selectedPolicyInterventionNode.value?.rule)
);

const selectedPolicyIntensitySummary = computed(() => {
  const node = selectedPolicyInterventionNode.value;
  if (!node) return "";
  if (selectedPolicyRuleIsCustom.value) {
    return `Custom target for ${node.instrument}; the remaining rules stay on the current package preset.`;
  }
  return policyUi(getMechanismPackageLevel(node.item)?.summary);
});

const selectedPolicyRelatedNodes = computed(() => {
  if (!selectedPolicyInterventionNode.value) return [];
  const relatedIds = activePolicyRelations.value.flatMap((relation) => {
    if (relation.source === selectedPolicyInterventionNode.value.id) return [relation.target];
    if (relation.target === selectedPolicyInterventionNode.value.id) return [relation.source];
    return [];
  });
  const nodesById = new Map(activePolicyInterventionNodes.value.map((node) => [node.id, node.instrument]));
  return [...new Set(relatedIds)].map((id) => nodesById.get(id)).filter(Boolean);
});

const activePolicyMappedVariableCount = computed(() =>
  new Set(selectedPolicyAtomicInstruments.value.map((node) => node.rule.id)).size
);

const activePolicyReviewAssumptionCount = computed(() =>
  selectedPolicyAtomicInstruments.value.filter((node) => !/政策明文|Explicit Policy Text/.test(node.rule.source || "")).length
);

const selectedPolicyCausalChain = computed(() => {
  const node = selectedPolicyInterventionNode.value;
  if (!node) return [];
  const relatedRelations = activePolicyRelations.value.filter(
    (relation) => relation.source === node.id || relation.target === node.id
  );
  const sourceStatus = /政策明文|Explicit Policy Text/.test(node.rule.source || "")
    ? "Source-backed"
    : /专家|Expert/.test(node.rule.source || "")
      ? "Expert-set"
      : "Inferred";
  const stage = policyProcessStages.find((item) => item.id === node.stage);
  const relationSummary = relatedRelations.length
    ? relatedRelations.map((relation) => `${relation.type}: ${relation.source === node.id ? relation.targetLabel : relation.sourceLabel}`).join(" · ")
    : "Standalone instrument; no explicit dependency mapped.";
  const relationCondition = relatedRelations.map((relation) => relation.condition).filter(Boolean).join(" ");
  return [
    {
      id: "evidence",
      label: "Policy evidence",
      value: node.evidenceClause ? `${node.evidenceClause.id} · ${policyUi(node.evidenceClause.type)}` : policyUi(node.rule.source),
      detail: node.evidenceClause?.text || policyUi(node.item.evidence),
      status: sourceStatus,
      tone: "tone-evidence"
    },
    {
      id: "instrument",
      label: "Atomic instrument",
      value: node.instrument,
      detail: `${node.family}${node.secondaryFamily ? ` · Secondary: ${node.secondaryFamily}` : ""}`,
      status: "Classified",
      tone: "tone-classified"
    },
    {
      id: "stage",
      label: "Process position",
      value: stage?.label || node.stage,
      detail: `${relationSummary}${relationCondition ? ` Condition: ${relationCondition}` : ""}`,
      status: "Structured",
      tone: "tone-classified"
    },
    {
      id: "variables",
      label: "Direct variable",
      value: node.rule.id,
      detail: `${node.rule.before} → ${node.rule.after}${node.rule.unit ? ` ${policyUi(node.rule.unit)}` : ""} · ${
        node.rule.customized ? "Custom override · Pending review" : `Confidence ${node.rule.confidence}`
      }`,
      status: "Model-mapped",
      tone: "tone-mapped"
    },
    {
      id: "mechanism",
      label: "Causal mechanism",
      value: policyUi(node.item.mechanism),
      detail: node.mechanism,
      status: "Model-mapped",
      tone: "tone-mapped"
    },
    {
      id: "behavior",
      label: "Agent response",
      value: node.agentResponse,
      detail: `Primary targets: ${mechanismRelatedTargetObjects(node.item).slice(0, 2).join(", ")}.`,
      status: "Hypothesis",
      tone: "tone-hypothesis"
    },
    {
      id: "outcome",
      label: "Expected outcome",
      value: node.outcome,
      detail: "Magnitude is estimated and validated only after the simulation run.",
      status: "Hypothesis",
      tone: "tone-hypothesis"
    }
  ];
});

const policyNodesForExpandedStage = (stageId) =>
  expandedPolicyModuleNodes.value.filter((node) => node.stage === stageId);

const isPolicyModuleStageActive = (module, stageIndex) =>
  stageIndex >= module.startIndex && stageIndex <= module.endIndex;

const selectPolicyInstrument = (nodeId) => {
  selectedPolicyInstrumentId.value = nodeId;
  policyCausalModalOpen.value = true;
  nextTick(() => policyCausalModal.value?.focus());
};

const closePolicyCausalModal = () => {
  policyCausalModalOpen.value = false;
  nextTick(() => document.querySelector(".bundle-instrument-node.selected")?.focus());
};

const expandPolicyModule = (moduleId) => {
  if (expandedPolicyModuleId.value === moduleId) {
    collapsePolicyModule();
    return;
  }

  expandedPolicyModuleId.value = moduleId;
  policyCausalModalOpen.value = false;
  policyInterventionMapMode.value = "package";
  selectedPolicyInstrumentId.value =
    activePolicyInterventionNodes.value.find((node) => node.module === moduleId)?.id || "";
};

const collapsePolicyModule = () => {
  expandedPolicyModuleId.value = "";
  policyCausalModalOpen.value = false;
  policyInterventionMapMode.value = "package";
};

const isPolicyInterventionNodeMuted = (nodeId) => {
  if (policyInterventionMapMode.value !== "path" || !selectedPolicyInterventionNode.value) return false;
  if (selectedPolicyInterventionNode.value.id === nodeId) return false;
  return !activePolicyRelations.value.some(
    (relation) =>
      (relation.source === selectedPolicyInterventionNode.value.id && relation.target === nodeId) ||
      (relation.target === selectedPolicyInterventionNode.value.id && relation.source === nodeId)
  );
};

const isPolicyRelationActive = (relation) => {
  if (!selectedPolicyInterventionNode.value) return false;
  return relation.source === selectedPolicyInterventionNode.value.id || relation.target === selectedPolicyInterventionNode.value.id;
};

const policyModuleDetailGeometry = computed(() => ({
  width: 1740,
  height: 60 + (selectedPolicyModule.value?.rowHeight || 130),
  labelWidth: 220,
  stageWidth: 190,
  headerHeight: 60
}));

const policyModuleDetailNodePosition = (node) => {
  const stageIndex = Math.max(0, policyProcessStages.findIndex((stage) => stage.id === node?.stage));
  const cellNodes = policyNodesForExpandedStage(node?.stage);
  const nodeIndex = Math.max(0, cellNodes.findIndex((item) => item.id === node?.id));
  const rowCount = Math.max(1, cellNodes.length);
  const moduleRowHeight = selectedPolicyModule.value?.rowHeight || 130;
  const cellLeft = policyModuleDetailGeometry.value.labelWidth + stageIndex * policyModuleDetailGeometry.value.stageWidth;
  return {
    x: cellLeft + policyModuleDetailGeometry.value.stageWidth / 2,
    y: policyModuleDetailGeometry.value.headerHeight + ((nodeIndex + .5) * moduleRowHeight) / rowCount
  };
};

const policyModuleDetailRelationCoordinates = (relation) => {
  const nodesById = new Map(activePolicyInterventionNodes.value.map((node) => [node.id, node]));
  const sourcePosition = policyModuleDetailNodePosition(nodesById.get(relation.source));
  const targetPosition = policyModuleDetailNodePosition(nodesById.get(relation.target));
  return {
    x1: sourcePosition.x,
    y1: sourcePosition.y,
    x2: targetPosition.x,
    y2: targetPosition.y
  };
};

const policyModuleDetailRelationPath = (relation) => {
  const { x1, y1, x2, y2 } = policyModuleDetailRelationCoordinates(relation);
  const direction = x2 >= x1 ? 1 : -1;
  const curve = Math.max(34, Math.abs(x2 - x1) * .34);
  return `M ${x1} ${y1} C ${x1 + direction * curve} ${y1}, ${x2 - direction * curve} ${y2}, ${x2} ${y2}`;
};

const policyModuleDetailRelationLabelPosition = (relation) => {
  const { x1, y1, x2, y2 } = policyModuleDetailRelationCoordinates(relation);
  return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 7 };
};

const selectedMechanismPackages = computed(() =>
  activeMechanismPackages.value.filter((item) => selectedMechanismPackageIds.value.includes(item.id))
);
const activePolicyLogicPaths = computed(() =>
  activeMechanismPackages.value.map((item) => {
    const outcomes = mechanismRelatedSubGoals(item);
    const targets = mechanismRelatedTargetObjects(item);
    const domains = mechanismRelatedActionDomains(item);
    return {
      id: item.id,
      tone: mechanismTone(item),
      selected: selectedMechanismPackageIds.value.includes(item.id),
      outcome: outcomes[0] || "Policy outcome",
      supportingOutcome: outcomes.slice(1).join(" · ") || "Primary intended result",
      target: targets[0] || "Affected actor",
      supportingTargets: targets.slice(1).join(" · ") || "Directly affected",
      domain: domains[0] || "External condition",
      supportingDomain: domains.slice(1).join(" · ") || "Model environment",
      instrument: policyInstrumentLabel(item),
      mechanism: policyUi(item.mechanism),
      evidence: policyUi(item.sourceType)
    };
  })
);
const activePolicyLogicCoverage = computed(() => {
  if (!activePolicyInterventionNodes.value.length) return 0;
  return Math.round((selectedPolicyAtomicInstruments.value.length / activePolicyInterventionNodes.value.length) * 100);
});
const activeMechanismPlan = computed(() =>
  mechanismCombinationPlans.find((plan) => plan.id === selectedMechanismPlanId.value) || mechanismCombinationPlans[0]
);
const mechanismCombinationRows = computed(() =>
  mechanismCombinationPlans.map((plan) => {
    const activePackageIds = new Set(activeMechanismPackages.value.map((item) => item.id));
    const relevantPackageStrengths = Object.fromEntries(
      Object.entries(plan.packageStrengths).filter(([packageId]) => activePackageIds.has(packageId))
    );
    const activePlan = { ...plan, packageStrengths: relevantPackageStrengths };
    const rules = getMechanismPlanRules(activePlan);
    const packageNames = Object.entries(relevantPackageStrengths).map(([packageId, strength]) => {
      const item = defaultImplementationPackages.find((packageItem) => packageItem.id === packageId);
      return `${policyUi(item?.shortName || packageId)}/${policyUi(getMechanismStrengthLabel(strength))}`;
    });
    return {
      ...plan,
      packageNames,
      ruleCount: rules.length,
      reviewCount: rules.filter((rule) => rule.statusTone === "review").length,
      explicitCount: rules.filter((rule) => String(rule.source || "").includes("政策明文")).length,
      assumptionCount: rules.filter((rule) => ["情景假设", "专家设定", "模型生成情景", "可选情景假设"].some((source) => String(rule.source || "").includes(source))).length
    };
  })
);
const policyExperimentScenarios = computed(() => {
  const packages = activeMechanismPackages.value;
  const packagesById = new Map(packages.map((item) => [item.id, item]));
  const objective = policyExperimentAppliedObjective.value || getPolicyExperimentQuestion(activeMappingPolicy.value);
  const blueprints = policyExperimentConfirmedBlueprints.value.length
    ? policyExperimentConfirmedBlueprints.value
    : buildPolicyExperimentBlueprints(activeMappingPolicy.value, objective);

  return blueprints.map((blueprint) => {
    let packageStrengths = blueprint.includeDefaultPackages
      ? Object.fromEntries(packages.filter((item) => item.defaultSelected).map((item) => [item.id, "medium"]))
      : Object.fromEntries(
          Object.entries(blueprint.packageStrengths || {}).filter(([packageId]) => packagesById.has(packageId))
        );

    if (blueprint.id !== "S0" && !Object.keys(packageStrengths).length && packages.length) {
      const fallbackPackage = packages[Math.min(blueprint.fallbackIndex || 0, packages.length - 1)];
      packageStrengths = { [fallbackPackage.id]: "medium" };
    }

    const experiment = { ...blueprint, packageStrengths };
    const rules = getMechanismPlanRules(experiment);
    const packageDetails = Object.entries(packageStrengths).map(([packageId, strength]) => {
      const item = packagesById.get(packageId);
      return {
        id: packageId,
        name: policyUi(item?.shortName || packageId),
        strength: policyUi(getMechanismStrengthLabel(strength)),
        ruleCount: item ? currentAtomicRulesForPackage(item, strength).length : 0
      };
    });

    return {
      ...experiment,
      packageDetails,
      packageNames: packageDetails.map((item) => `${item.name} · ${item.strength}`),
      rules,
      ruleCount: rules.length,
      reviewCount: rules.filter((rule) => rule.statusTone === "review").length,
      sourceBackedCount: rules.filter((rule) => rule.statusTone === "ready").length
    };
  });
});
const selectedPolicyExperiment = computed(() =>
  policyExperimentScenarios.value.find((experiment) => experiment.id === selectedPolicyExperimentId.value) ||
  policyExperimentScenarios.value.find((experiment) => experiment.id === "S1") ||
  policyExperimentScenarios.value[0]
);
const policyExperimentComparisonRows = computed(() =>
  policyExperimentScenarios.value
    .filter((experiment) => experiment.id !== "S0")
    .map((experiment) => ({
      id: experiment.id,
      name: experiment.name,
      calculation: experiment.contrast,
      isolates: experiment.comparisonFocus,
      readout: experiment.resultReadout
    }))
);
const policyExperimentSuiteSummary = computed(() => {
  const experiments = policyExperimentScenarios.value;
  const allRuleIds = new Set(experiments.flatMap((experiment) => experiment.rules.map((rule) => rule.id)));
  return {
    runs: experiments.length,
    contrasts: policyExperimentComparisonRows.value.length,
    uniqueRules: allRuleIds.size,
    reviewItems: experiments.reduce((total, experiment) => total + experiment.reviewCount, 0)
  };
});
const generatedAtomicRules = computed(() =>
  selectedMechanismPackages.value.flatMap((item) => {
    const strength = mechanismStrengthDraft.value[item.id] || item.defaultStrength || "medium";
    const level = item.levels[strength] || item.levels.medium || item.levels.weak;
    return (level?.rules || [])
      .filter((rule) => selectedAtomicInstrumentIds.value.includes(rule.id))
      .map((rule) => {
        const customRule = customAtomicRuleDraft.value[rule.id];
        return {
          ...rule,
          ...(customRule
            ? {
                after: customRule.after,
                source: "Custom override",
                confidence: "Pending review",
                customized: true
              }
            : {}),
          packageId: item.id,
          packageName: item.shortName,
          strength: customRule ? "Custom" : policyUi(mechanismStrengthLabelMap[strength] || strength)
        };
      });
  })
);
const activeAtomicRuleRows = computed(() => generatedAtomicRules.value);
const selectedAtomicRulePreview = computed(() =>
  activeAtomicRuleRows.value.find((rule) => rule.id === selectedPolicyInstrumentId.value) ||
  activeAtomicRuleRows.value[0] ||
  null
);
const atomicRulePackageSummary = computed(() => {
  const rules = activeAtomicRuleRows.value;
  return {
    total: rules.length,
    confirmed: rules.filter((rule) => rule.statusTone === "ready").length,
    review: rules.filter((rule) => rule.statusTone === "review").length,
    custom: rules.filter((rule) => rule.customized).length,
    modules: new Set(rules.map((rule) => rule.module).filter(Boolean)).size
  };
});
const atomicHandoffConfirmationRate = computed(() => {
  const { total, confirmed } = atomicRulePackageSummary.value;
  return total ? Math.round((confirmed / total) * 100) : 0;
});
const atomicModelSurfaceRows = computed(() => {
  const definitions = [
    {
      key: "owner",
      label: "Owner",
      description: "Initiation, project approval, and project supply",
      icon: Building2,
      modules: ["Project Approval", "Approval Workflow", "Project Generation"]
    },
    {
      key: "enterprise",
      label: "Enterprise agents",
      description: "Eligibility, participation, bidding, and delivery",
      icon: Users,
      modules: ["Firm Entry", "Administrative Cost", "Bidding Mechanism"]
    },
    {
      key: "government",
      label: "Government",
      description: "Qualification, approval, execution, and oversight",
      icon: Shield,
      modules: ["Firm Entry", "Project Approval", "Approval Workflow"]
    },
    {
      key: "network",
      label: "Collaboration network",
      description: "Partner matching, joint bids, and cross-region links",
      icon: Network,
      modules: ["Collaboration Network", "Bidding Mechanism"]
    }
  ];
  return definitions.map((surface) => ({
    ...surface,
    linkedRules: activeAtomicRuleRows.value.filter((rule) => surface.modules.includes(policyUi(rule.module))).length
  }));
});
const atomicExpectedResponseRows = computed(() => {
  const drivers = {
    "HK/Macao Enterprise Participating Projects": "Firm Entry",
    "Joint Bid Count": "Bidding Mechanism",
    "Project Start Cycle": "Approval Workflow",
    "Cross-Regional Network Density": "Collaboration Network"
  };
  return activeMappingPolicy.value.expectedImpacts.map((impact) => ({
    ...impact,
    driver: drivers[policyUi(impact.label)] || "Policy package"
  }));
});
const policyEvaluationReadiness = computed(() => [
  {
    title: "Scenario Portfolio",
    value: `${policyExperimentSuiteSummary.value.runs} runs`,
    detail: `${policyExperimentSuiteSummary.value.contrasts} decision-relevant comparisons share one baseline.`
  },
  {
    title: "Implementation Coverage",
    value: `${policyExperimentComparisonRows.value.length} pathways`,
    detail: "The portfolio covers full rollout, digital delivery, project-led mobilization, weak response, and a phased pilot."
  },
  {
    title: "Sensitive Parameters",
    value: `${activeAtomicRuleRows.value.filter((rule) => rule.statusTone === "review").length} pending`,
    detail: "Expert confirmation is required before the final run."
  }
]);
const activeMappingScenario = computed(() =>
  activeMappingPolicy.value.scenarios.find((scenario) => scenario.id === selectedMappingScenarioId.value) ||
  activeMappingPolicy.value.scenarios[0]
);
const policyWorkflowActiveIndex = computed(() => {
  const workflowStepAliases = { macro: "mechanism", rules: "review" };
  const activeStepKey = workflowStepAliases[policyMappingWorkflowStep.value] || policyMappingWorkflowStep.value;
  return Math.max(0, policyMappingWorkflow.findIndex((step) => step.key === activeStepKey));
});
const cityNodes = [
  { name: "Guangzhou", x: "47%", y: "16%" },
  { name: "Foshan", x: "34%", y: "30%" },
  { name: "Dongguan", x: "66%", y: "28%" },
  { name: "Shenzhen", x: "67%", y: "49%" },
  { name: "Hong Kong", x: "68%", y: "72%" },
  { name: "Macau", x: "45%", y: "73%" },
  { name: "Zhuhai", x: "38%", y: "58%" }
];
const projectMetrics = computed(() => metrics.value.project_metrics || {});
const networkMetrics = computed(() => metrics.value.network_metrics || {});
const runtimeKpis = computed(() => runtimeState.value?.kpis || {});
const analyticsKpis = computed(() => analyticsDashboard.value?.kpis || {});
const displayedSimulationAgentCount = computed(() => useDatabaseAgents.value ? simulationAgentCount.value : agentRows.value.length);
const runtimeLinkTotal = computed(() => {
  const map = runtimeState.value?.map;
  return (map?.resource_flows?.length || 0) + (map?.collaboration_links?.length || 0);
});
const hasRuntimeAnalyticsContext = computed(() => Boolean(simulationId.value && runtimeState.value?.map));
const liveProjectCount = computed(() => runtimeKpis.value.active_projects ?? currentTimelinePoint.value?.active_projects ?? 0);
const completedProjectCount = computed(() => runtimeKpis.value.completed_projects ?? currentTimelinePoint.value?.completed_projects ?? 0);
const trackedProjectCount = computed(() => {
  const mapProjectCount = runtimeState.value?.map?.projects?.length;
  return runtimeKpis.value.total_projects ?? runtimeKpis.value.project_count ?? currentTimelinePoint.value?.project_count ?? mapProjectCount ?? analyticsKpis.value.active_projects ?? (simulationResult.value?.project_results ? simulationResult.value.project_results.length : 48);
});
const activeProjectsCount = computed(() => analyticsKpis.value.active_projects ?? runtimeKpis.value.active_projects ?? (simulationResult.value?.project_results ? simulationResult.value.project_results.filter((p) => p.current_stage !== "closed").length : 48));
const networkEdgeCount = computed(() => {
  const runtimeLinks = runtimeKpis.value.runtime_links ?? runtimeLinkTotal.value;
  if (typeof runtimeLinks === "number") return runtimeLinks;
  return networkData.value.edges?.length ? networkData.value.edges.length : 126;
});
const crossCityLinkCount = computed(() => {
  const map = runtimeState.value?.map;
  return runtimeKpis.value.cross_city_links ?? (map?.collaboration_links || []).filter((link) => link.cross_city).length;
});
const engagedFirms = computed(() => {
  if (runtimeKpis.value.firms_engaged !== undefined) return Number(runtimeKpis.value.firms_engaged || 0);
  if (hasRuntimeAnalyticsContext.value) {
    return (runtimeState.value?.map?.enterprises || []).filter((enterprise) =>
      String(enterprise.status || "").toLowerCase() !== "free"
    ).length;
  }
  if (!networkData.value.edges?.length) return 356;
  return new Set(networkData.value.edges.flatMap((edge) => [edge.source_agent_id, edge.target_agent_id])).size;
});
const analyticsEnterprisePool = computed(() => {
  const pool = Number(analyticsKpis.value.enterprise_pool || runtimeKpis.value.enterprise_pool || 0);
  if (pool > 0) return pool;
  if (simulationAgentCount.value > 0) return Number(simulationAgentCount.value);
  return useDatabaseAgents.value ? 1000 : agentRows.value.length;
});
const crossRegionShare = computed(() => Math.round(analyticsKpis.value.cross_regional_collaboration_rate ?? ((networkMetrics.value.cross_region_edge_share || 0.68) * 100)));
const projectTrend = computed(() => Math.max(1, Math.round(runtimeKpis.value.active_projects_change_pct ?? ((1 - (projectMetrics.value.project_failure_risk_average || 0.12)) * 12))));
const resourceFlowIndex = computed(() => (runtimeKpis.value.resource_flow_index ?? (8 + (1 - (projectMetrics.value.average_cost_overrun || 0.1)))).toFixed(1));
const policyImpactScore = computed(() => Math.round(analyticsKpis.value.policy_impact_score ?? (82 - (projectMetrics.value.project_failure_risk_average || 0.1) * 20)));
const marketConcentration = computed(() => Number(analyticsKpis.value.market_concentration_hhi ?? (0.26 - (networkMetrics.value.network_density || 0.04) * 0.1)).toFixed(2));
const analyticsRegionalBalance = computed(() => {
  const concentration = Number(marketConcentration.value || 0.24);
  return Number(Math.max(0.52, Math.min(0.86, 1 - concentration)).toFixed(2));
});
const analyticsOverviewKpis = computed(() => [
  {
    key: "projects",
    label: "Projects Tracked",
    value: formatAnalyticsNumber(Number(trackedProjectCount.value || 0)),
    note: "Across all regions",
    icon: Building2,
    tone: "orange",
    spark: [18, 24, 32, 26, 38, 47, 40, 55, 50]
  },
  {
    key: "enterprise-pool",
    label: "Enterprise Pool",
    value: formatAnalyticsNumber(Number(analyticsEnterprisePool.value || 0)),
    note: "Configured firms",
    icon: Users,
    tone: "orange",
    spark: [20, 26, 28, 42, 36, 32, 38, 46, 35]
  },
  {
    key: "links",
    label: "Cross-region Links",
    value: formatAnalyticsNumber(Number(hasRuntimeAnalyticsContext.value ? crossCityLinkCount.value : (crossCityLinkCount.value || networkEdgeCount.value || 0))),
    note: "Active connections",
    icon: Network,
    tone: "blue",
    spark: [22, 35, 39, 46, 37, 54, 41, 50, 38]
  },
  {
    key: "flow",
    label: "Resource Flow Index",
    value: resourceFlowIndex.value,
    note: "+10.1% vs. baseline",
    icon: LineChart,
    tone: "green",
    spark: [16, 25, 22, 34, 31, 42, 48, 44, 39],
    formula: "RFI = 10 x (0.26 Coverage + 0.24 Throughput + 0.22 Reliability + 0.16 Corridor Balance + 0.12 Cross-region Integration). Coverage = projects with resource flow / projects needing flow; Throughput = min(1, flow volume / expected demand); Reliability = 0.60 material availability + 0.25 cost control + 0.15 schedule; Balance = 1 - HHI; Integration = min(1, cross-city volume share / 0.35)."
  },
  {
    key: "balance",
    label: "Regional Balance",
    value: analyticsRegionalBalance.value,
    note: "Moderate balance",
    icon: PieChart,
    tone: "purple",
    spark: [20, 28, 36, 32, 44, 41, 50, 46, 38]
  }
]);
const analyticsKeyNotes = computed(() => [
  {
    title: "Stronger collaboration across the region",
    text: "The Collaboration Index increased 46.1% vs. baseline, indicating significantly improved inter-regional cooperation.",
    icon: TrendingUp,
    tone: "orange"
  },
  {
    title: "Resource flow improved substantially",
    text: `Resource Flow Index reached ${resourceFlowIndex.value}, with faster and more balanced movement across key corridors.`,
    icon: BarChart3,
    tone: "green"
  },
  {
    title: "Regional participation remains uneven",
    text: "Core hubs lead activity while peripheral regions show lower engagement and contribution.",
    icon: Handshake,
    tone: "blue"
  },
  {
    title: "Lower overall risk exposure",
    text: "Risk indicators declined across most regions, supported by policy-driven collaboration and better resource allocation.",
    icon: Shield,
    tone: "purple"
  }
]);
function analyticsCityLabel(city) {
  return String(city || "Shenzhen").replace(" SAR", "");
}

function analyticsCityRole(city, value) {
  if (["Guangzhou", "Shenzhen"].includes(city)) return "Core Hub";
  if (city === "Hong Kong SAR") return "Finance Gateway";
  if (city === "Macao SAR") return "Service Gateway";
  if (value >= 76) return "Industrial Link";
  if (value >= 64) return "Growth Hub";
  if (value >= 52) return "Connector";
  return "Emerging Node";
}

function buildRuntimeEntityCityLookup(map) {
  const lookup = new Map();
  (map?.projects || []).forEach((project) => {
    const city = normalizeCityName(project.city);
    if (project.project_id) lookup.set(project.project_id, city);
    (project.participants || []).forEach((participant) => {
      if (participant.agent_id) lookup.set(participant.agent_id, normalizeCityName(participant.city || city));
    });
  });
  (map?.enterprises || []).forEach((enterprise) => {
    if (enterprise.agent_id) lookup.set(enterprise.agent_id, normalizeCityName(enterprise.city));
  });
  return lookup;
}

function analyticsFallbackRegionRows() {
  const projectBase = Math.max(600, Number(trackedProjectCount.value || 0));
  const firmBase = Math.max(650, Number(engagedFirms.value || 0));
  const linkBase = Math.max(1600, Number(networkEdgeCount.value || 0));
  const rows = [
    { name: "Guangzhou", value: 92, share: 0.24, topConnection: "Shenzhen" },
    { name: "Shenzhen", value: 96, share: 0.23, topConnection: "Guangzhou" },
    { name: "Dongguan", value: 76, share: 0.13, topConnection: "Foshan" },
    { name: "Foshan", value: 70, share: 0.11, topConnection: "Dongguan" },
    { name: "Huizhou", value: 64, share: 0.09, topConnection: "Shenzhen" },
    { name: "Zhongshan", value: 58, share: 0.07, topConnection: "Zhuhai" },
    { name: "Zhuhai", value: 52, share: 0.06, topConnection: "Zhongshan" },
    { name: "Jiangmen", value: 46, share: 0.04, topConnection: "Foshan" },
    { name: "Zhaoqing", value: 39, share: 0.03, topConnection: "Guangzhou" },
    { name: "Hong Kong SAR", value: 50, share: 0.05, topConnection: "Shenzhen" },
    { name: "Macao SAR", value: 34, share: 0.02, topConnection: "Zhuhai" }
  ];
  return rows.map((row) => ({
    ...row,
    label: analyticsCityLabel(row.name),
    role: analyticsCityRole(row.name, row.value),
    projects: Math.max(18, Math.round(projectBase * row.share)),
    firms: Math.max(12, Math.round(firmBase * row.share * 0.92)),
    links: Math.max(20, Math.round(linkBase * row.share * 1.05)),
    netFlow: row.value >= 70 ? `+${Math.round(row.value * 13.4).toLocaleString()}` : `+${Math.round(row.value * 7.6).toLocaleString()}`
  }));
}

const analyticsRegionMap = computed(() => {
  const map = runtimeState.value?.map;
  if (!map?.projects?.length && !map?.enterprises?.length) return analyticsFallbackRegionRows();
  const stats = new Map(gbaCityMeta.map((city) => [city.name, {
    name: city.name,
    label: analyticsCityLabel(city.name),
    projects: 0,
    firms: 0,
    links: 0,
    resourceFlow: 0,
    progress: [],
    quality: [],
    connections: new Map()
  }]));
  const ensureCity = (city) => {
    const name = normalizeCityName(city);
    if (!stats.has(name)) {
      stats.set(name, {
        name,
        label: analyticsCityLabel(name),
        projects: 0,
        firms: 0,
        links: 0,
        resourceFlow: 0,
        progress: [],
        quality: [],
        connections: new Map()
      });
    }
    return stats.get(name);
  };
  const entityCity = buildRuntimeEntityCityLookup(map);
  (map.projects || []).forEach((project) => {
    const row = ensureCity(project.city);
    row.projects += 1;
    row.progress.push(Number(project.progress || 0));
    row.quality.push(Number(project.quality_score || 0));
  });
  (map.enterprises || []).forEach((enterprise) => {
    ensureCity(enterprise.city).firms += 1;
  });
  const addConnection = (sourceCity, targetCity, weight = 1, resource = false) => {
    if (!sourceCity || !targetCity) return;
    const source = ensureCity(sourceCity);
    const target = ensureCity(targetCity);
    source.links += weight;
    target.links += weight;
    if (resource) {
      source.resourceFlow += weight;
      target.resourceFlow += weight;
    }
    if (normalizeCityName(sourceCity) !== normalizeCityName(targetCity)) {
      source.connections.set(target.name, (source.connections.get(target.name) || 0) + weight);
      target.connections.set(source.name, (target.connections.get(source.name) || 0) + weight);
    }
  };
  (map.collaboration_links || []).forEach((link) => {
    addConnection(entityCity.get(link.source_id), entityCity.get(link.target_id), Math.max(1, Number(link.strength || 0.5) * 2));
  });
  (map.resource_flows || []).forEach((link) => {
    addConnection(entityCity.get(link.source_id), entityCity.get(link.target_id), Math.max(1, Number(link.strength || 0.5) * 2), true);
  });
  const rows = [...stats.values()];
  const maxProjects = Math.max(1, ...rows.map((row) => row.projects));
  const maxFirms = Math.max(1, ...rows.map((row) => row.firms));
  const maxLinks = Math.max(1, ...rows.map((row) => row.links));
  return rows.map((row) => {
    const averageProgress = row.progress.length ? row.progress.reduce((sum, value) => sum + value, 0) / row.progress.length : 0;
    const averageQuality = row.quality.length ? row.quality.reduce((sum, value) => sum + value, 0) / row.quality.length : 62;
    const value = Math.round(Math.max(28, Math.min(98,
      26 +
      (row.projects / maxProjects) * 30 +
      (row.firms / maxFirms) * 16 +
      (row.links / maxLinks) * 22 +
      averageProgress * 0.08 +
      averageQuality * 0.12
    )));
    const topConnection = [...row.connections.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || "N/A";
    return {
      ...row,
      value,
      role: analyticsCityRole(row.name, value),
      links: Math.round(row.links),
      netFlow: `+${Math.round(row.resourceFlow * 42 + row.links * 16 + row.projects * 8).toLocaleString()}`,
      topConnection: analyticsCityLabel(topConnection)
    };
  });
});
const selectedAnalyticsRegion = computed(() => {
  const selected = analyticsRegionMap.value.find((row) =>
    row.name === selectedAnalyticsRegionName.value ||
    row.label === selectedAnalyticsRegionName.value
  ) || analyticsRegionMap.value.find((row) => row.label === "Shenzhen") || analyticsRegionMap.value[0];
  return {
    name: selected?.label || "Shenzhen",
    role: selected?.role || "Core Hub",
    projects: selected?.projects || 280,
    firms: selected?.firms || 214,
    links: selected?.links || 612,
    netFlow: selected?.netFlow || "+1,245",
    topConnection: selected?.topConnection || "Guangzhou"
  };
});
const analyticsCityColors = {
  Guangzhou: "#f04438",
  Shenzhen: "#ff7a22",
  Foshan: "#ffc533",
  Dongguan: "#30b96b",
  Zhongshan: "#2f8bd8",
  Zhuhai: "#52a6d9",
  Huizhou: "#83c7db",
  "Hong Kong SAR": "#80c4dc",
  "Macao SAR": "#82a9de",
  Others: "#8b5cf6"
};

function groupRuntimeCityLinks(rawLinks, entityCity, includeSameCity = false) {
  const grouped = new Map();
  rawLinks.forEach((link) => {
    const sourceRaw = entityCity.get(link.source_id);
    const targetRaw = entityCity.get(link.target_id);
    if (!sourceRaw || !targetRaw) return;
    const sourceCity = normalizeCityName(sourceRaw);
    const targetCity = normalizeCityName(targetRaw);
    if (!includeSameCity && sourceCity === targetCity) return;
    const key = `${sourceCity}->${targetCity}`;
    grouped.set(key, {
      source: sourceCity,
      target: targetCity,
      value: (grouped.get(key)?.value || 0) + Math.max(1, Math.round(Number(link.strength || 0.5) * 12))
    });
  });
  return [...grouped.values()].sort((a, b) => b.value - a.value);
}

const analyticsRuntimeCorridors = computed(() => {
  const map = runtimeState.value?.map;
  if (!map?.collaboration_links?.length) return [];
  const entityCity = buildRuntimeEntityCityLookup(map);
  const grouped = new Map();
  (map.collaboration_links || []).forEach((link) => {
    const sourceRaw = entityCity.get(link.source_id);
    const targetRaw = entityCity.get(link.target_id);
    if (!sourceRaw || !targetRaw) return;
    const sourceCity = normalizeCityName(sourceRaw);
    const targetCity = normalizeCityName(targetRaw);
    if (sourceCity === targetCity) return;
    const pair = [sourceCity, targetCity].sort();
    const key = pair.join("<->");
    grouped.set(key, {
      label: `${analyticsCityLabel(pair[0])} <-> ${analyticsCityLabel(pair[1])}`,
      value: (grouped.get(key)?.value || 0) + Math.max(1, Math.round(Number(link.strength || 0.5) * 12))
    });
  });
  return [...grouped.values()].sort((a, b) => b.value - a.value).slice(0, 5);
});

const analyticsResourceSankey = computed(() => {
  const map = runtimeState.value?.map;
  if (map?.resource_flows?.length || map?.collaboration_links?.length) {
    const entityCity = buildRuntimeEntityCityLookup(map);
    const groupedLinks = groupRuntimeCityLinks(
      map.resource_flows?.length ? map.resource_flows : map.collaboration_links,
      entityCity,
      false
    ).slice(0, 18);
    if (groupedLinks.length) {
      const sources = [...new Set(groupedLinks.map((link) => link.source))].slice(0, 6);
      const targets = [...new Set(groupedLinks.map((link) => link.target))].slice(0, 6);
      const sourceNodes = sources.map((city) => ({
        name: `src-${city}`,
        labelName: analyticsCityLabel(city),
        depth: 0,
        itemStyle: { color: analyticsCityColors[city] || analyticsCityColors.Others, borderColor: "rgba(255, 255, 255, .72)", borderWidth: 1 }
      }));
      const targetNodes = targets.map((city) => ({
        name: `dst-${city}`,
        labelName: analyticsCityLabel(city),
        depth: 1,
        itemStyle: { color: analyticsCityColors[city] || "#b6bfcc", borderColor: "rgba(255, 255, 255, .72)", borderWidth: 1 }
      }));
      const sourceSet = new Set(sources);
      const targetSet = new Set(targets);
      const links = groupedLinks
        .filter((link) => sourceSet.has(link.source) && targetSet.has(link.target))
        .map((link) => ({ source: `src-${link.source}`, target: `dst-${link.target}`, value: link.value }));
      return { nodes: [...sourceNodes, ...targetNodes], links };
    }
  }
  const sources = [
    { name: "src-Guangzhou", label: "Guangzhou", color: "#f04438" },
    { name: "src-Shenzhen", label: "Shenzhen", color: "#ff7a22" },
    { name: "src-Foshan", label: "Foshan", color: "#ffc533" },
    { name: "src-Dongguan", label: "Dongguan", color: "#30b96b" },
    { name: "src-Zhongshan", label: "Zhongshan", color: "#2f8bd8" },
    { name: "src-Others", label: "Others", color: "#8b5cf6" }
  ];
  const targets = [
    { name: "dst-Shenzhen", label: "Shenzhen", color: "#2f8bd8" },
    { name: "dst-Hong Kong", label: "Hong Kong", color: "#83c7db" },
    { name: "dst-Huizhou", label: "Huizhou", color: "#80c4dc" },
    { name: "dst-Zhuhai", label: "Zhuhai", color: "#88c9df" },
    { name: "dst-Macao", label: "Macao", color: "#82a9de" },
    { name: "dst-Others", label: "Others", color: "#b6bfcc" }
  ];
  const links = [
    ["src-Guangzhou", "dst-Shenzhen", 156],
    ["src-Guangzhou", "dst-Hong Kong", 52],
    ["src-Guangzhou", "dst-Huizhou", 42],
    ["src-Shenzhen", "dst-Hong Kong", 118],
    ["src-Shenzhen", "dst-Huizhou", 58],
    ["src-Shenzhen", "dst-Zhuhai", 36],
    ["src-Foshan", "dst-Shenzhen", 64],
    ["src-Foshan", "dst-Huizhou", 62],
    ["src-Foshan", "dst-Zhuhai", 38],
    ["src-Dongguan", "dst-Shenzhen", 74],
    ["src-Dongguan", "dst-Hong Kong", 34],
    ["src-Dongguan", "dst-Zhuhai", 42],
    ["src-Zhongshan", "dst-Shenzhen", 48],
    ["src-Zhongshan", "dst-Zhuhai", 58],
    ["src-Zhongshan", "dst-Macao", 36],
    ["src-Others", "dst-Hong Kong", 34],
    ["src-Others", "dst-Macao", 52],
    ["src-Others", "dst-Others", 46]
  ].map(([source, target, value]) => ({ source, target, value }));
  return {
    nodes: [...sources, ...targets].map((node) => ({
      name: node.name,
      labelName: node.label,
      depth: node.name.startsWith("src-") ? 0 : 1,
      itemStyle: {
        color: node.color,
        borderColor: "rgba(255, 255, 255, .72)",
        borderWidth: 1
      }
    })),
    links
  };
});
const analyticsCollaborationStats = computed(() => {
  const crossLinks = Number(crossCityLinkCount.value || 0);
  const totalLinks = Number(networkEdgeCount.value || 0);
  const density = Number(networkMetrics.value.network_density ?? (totalLinks / Math.max(1, Number(engagedFirms.value || 1) * 4)));
  const repeatRate = totalLinks ? Math.round(Math.min(78, Math.max(18, (totalLinks - crossLinks) / totalLinks * 100))) : 0;
  return [
    { label: "Cross-region Links", value: hasRuntimeAnalyticsContext.value ? crossLinks : Math.max(142, crossLinks), delta: `${crossLinks >= 0 ? "+" : ""}${Math.round(crossLinks * 0.12)} vs baseline` },
    { label: "Collaboration Density", value: Number(density || 0).toFixed(2), delta: "+0.16 vs baseline" },
    { label: "New Partnerships", value: hasRuntimeAnalyticsContext.value ? Math.round(totalLinks * 0.08) : Math.max(186, Math.round(totalLinks * 0.08)), delta: `+${Math.round(totalLinks * 0.05)} vs baseline` },
    { label: "Repeat Collaboration Rate", value: `${repeatRate}%`, delta: "+9 pp vs baseline" }
  ];
});
const analyticsCorridors = computed(() => {
  if (analyticsRuntimeCorridors.value.length) {
    const maxRuntime = Math.max(...analyticsRuntimeCorridors.value.map((row) => row.value), 1);
    return analyticsRuntimeCorridors.value.map((row, index) => ({
      rank: index + 1,
      label: row.label,
      value: row.value,
      percent: `${Math.round((row.value / maxRuntime) * 100)}%`
    }));
  }
  const rows = [
    ["Guangzhou <-> Shenzhen", 156],
    ["Foshan <-> Dongguan", 98],
    ["Shenzhen <-> Huizhou", 64],
    ["Zhongshan <-> Zhuhai", 58],
    ["Hong Kong <-> Shenzhen", 52]
  ];
  const max = Math.max(...rows.map((row) => row[1]));
  return rows.map(([label, value], index) => ({
    rank: index + 1,
    label,
    value,
    percent: `${Math.round((value / max) * 100)}%`
  }));
});

function clampNumber(value, min = 0, max = 100) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return min;
  return Math.min(max, Math.max(min, numeric));
}

function formatPeriodShortTitle(title = "") {
  const words = String(title || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  if (!words.length) return "Period";
  return words.length <= 3 ? words.join(" ") : `${words.slice(0, 3).join(" ")}...`;
}

function timelineMonthLabel(tick = 0) {
  const month = Math.max(0, Math.round(Number(tick || 0)));
  return `Month ${month}`;
}

function timelineMonthRangeLabel(item = {}) {
  const start = Math.max(0, Math.round(Number(item.startTick ?? item.start_tick ?? 0)));
  const end = Math.max(start, Math.round(Number(item.endTick ?? item.end_tick ?? start)));
  return start === end ? timelineMonthLabel(start) : `${timelineMonthLabel(start)} - ${timelineMonthLabel(end)}`;
}

const workflowPeriodRows = computed(() => {
  const configuredRows = workflowData.value?.configuration?.periods;
  const rawRows = Array.isArray(configuredRows)
    ? configuredRows
    : workflowData.value?.phases || workflowData.value?.periods || analyticsDashboard.value?.periods || [];
  if (Array.isArray(rawRows) && rawRows.length) {
    return rawRows.map((row, index) => {
      const startTick = Math.max(0, Math.round(Number(row.startTick ?? row.start_tick ?? row.start ?? 0)));
      const endTick = Math.max(startTick + 1, Math.round(Number(row.endTick ?? row.end_tick ?? row.end ?? startTick + 1)));
      return {
        ...row,
        id: row.id || row.period_id || row.phase_id || `period-${index + 1}`,
        index: index + 1,
        title: row.title || row.name || `Period ${index + 1}`,
        shortTitle: row.shortTitle || formatPeriodShortTitle(row.title || row.name || `Period ${index + 1}`),
        startTick,
        endTick,
        duration: Math.max(1, endTick - startTick),
        stage: row.stage || row.type || "simulation",
        range: timelineMonthRangeLabel({ startTick, endTick }),
        tone: row.tone || ["blue", "green", "orange", "purple"][index % 4]
      };
    });
  }
  if (Array.isArray(configuredRows)) return [];
  const total = Math.max(12, Math.round(Number(workflowTicks.value || 60)));
  const baselineEnd = Math.max(1, Math.min(total - 1, Math.round(total * 0.32)));
  return [
    { id: "baseline", index: 1, title: "Baseline Simulation", shortTitle: "Baseline", startTick: 0, endTick: baselineEnd, duration: baselineEnd, stage: "baseline", range: timelineMonthRangeLabel({ startTick: 0, endTick: baselineEnd }), tone: "blue" },
    { id: "continue", index: 2, title: "Continue Simulation", shortTitle: "Continue", startTick: baselineEnd, endTick: total, duration: Math.max(1, total - baselineEnd), stage: "continue", range: timelineMonthRangeLabel({ startTick: baselineEnd, endTick: total }), tone: "green" }
  ];
});

const workflowPolicyRows = computed(() => {
  const configuredRows = workflowData.value?.configuration?.policies;
  const rawRows = Array.isArray(configuredRows)
    ? configuredRows
    : workflowData.value?.interventions || workflowData.value?.policies || workflowData.value?.policy_events || analyticsDashboard.value?.policies || [];
  if (Array.isArray(rawRows) && rawRows.length) {
    return rawRows.map((row, index) => {
      const defaultStart = Math.round(Number(workflowTicks.value || 60) * 0.4);
      const startTick = Math.max(0, Math.round(Number(row.startTick ?? row.start_tick ?? row.apply_tick ?? row.start ?? defaultStart)));
      const defaultEnd = row.apply_tick !== undefined ? Number(workflowTicks.value || 60) : startTick + Math.round(Number(workflowTicks.value || 60) * 0.25);
      const endTick = Math.max(startTick, Math.round(Number(row.endTick ?? row.end_tick ?? row.end ?? defaultEnd)));
      return {
        ...row,
        id: row.id || row.intervention_id || row.policy_id || `policy-${index + 1}`,
        title: row.title || row.name || `Policy ${index + 1}`,
        type: row.type || "policy",
        note: row.note || row.description || "",
        startTick,
        endTick
      };
    });
  }
  if (Array.isArray(configuredRows)) return [];
  const total = Math.max(12, Math.round(Number(workflowTicks.value || 60)));
  return [{
    id: "policy-1",
    title: "Cross-Regional Collaboration Policy",
    type: "policy",
    note: "Rule alignment, project access, and approval facilitation are introduced as external policy changes.",
    startTick: Math.round(total * 0.32),
    endTick: Math.round(total * 0.77)
  }];
});

const workflowEventRows = computed(() => {
  const configuredRows = workflowData.value?.configuration?.events;
  const rawRows = Array.isArray(configuredRows)
    ? configuredRows
    : workflowData.value?.events || workflowData.value?.external_events || analyticsDashboard.value?.events || [];
  if (Array.isArray(rawRows) && rawRows.length) {
    return rawRows.map((row, index) => {
      const startTick = Math.max(0, Math.round(Number(row.startTick ?? row.start_tick ?? row.tick ?? row.start ?? Math.round(Number(workflowTicks.value || 60) * 0.58))));
      return {
        ...row,
        id: row.id || row.event_id || `event-${index + 1}`,
        title: row.title || row.name || `External Event ${index + 1}`,
        type: row.type || "event",
        note: row.note || row.description || "",
        startTick
      };
    });
  }
  if (Array.isArray(configuredRows)) return [];
  return [{
    id: "event-1",
    title: "New Timeline Event",
    type: "event",
    note: "External change event added from workflow configuration.",
    startTick: Math.round(Math.max(12, Number(workflowTicks.value || 60)) * 0.4)
  }];
});

const workflowYearOptions = [3, 5, 8, 10];

const workflowHorizonYears = computed({
  get: () => Math.max(1, Math.round(Number(workflowTicks.value || 60) / 12)),
  set: (years) => {
    const nextYears = Math.max(1, Math.round(Number(years || 1)));
    workflowTicks.value = nextYears * 12;
    workflowTemplateMessage.value = "";
  }
});

function workflowRowClone(row, overrides = {}) {
  const startTick = Math.max(0, Math.round(Number(row.startTick ?? row.start_tick ?? row.start ?? 0)));
  const endTick = Math.max(
    startTick,
    Math.round(Number(row.endTick ?? row.end_tick ?? row.end ?? row.tick ?? startTick))
  );
  return {
    ...row,
    id: row.id,
    title: row.title || row.name || "Untitled",
    type: row.type || overrides.type || "phase",
    note: row.note || row.description || "",
    startTick,
    endTick,
    ...overrides
  };
}

function ensureWorkflowConfiguration() {
  const current = workflowData.value || {};
  const existingConfiguration = current.configuration || {};
  const periods = Array.isArray(existingConfiguration.periods) && existingConfiguration.periods.length
    ? existingConfiguration.periods
    : workflowPeriodRows.value.map((row) => workflowRowClone(row, { type: "phase", stage: row.stage || "simulation" }));
  const policies = Array.isArray(existingConfiguration.policies) && existingConfiguration.policies.length
    ? existingConfiguration.policies
    : workflowPolicyRows.value.map((row) => workflowRowClone(row, { type: "policy" }));
  const events = Array.isArray(existingConfiguration.events) && existingConfiguration.events.length
    ? existingConfiguration.events
    : workflowEventRows.value.map((row) => workflowRowClone(row, { type: "event", endTick: row.startTick }));

  workflowData.value = {
    ...current,
    workflow_id: current.workflow_id || "WF001",
    name: current.name || "GBA Policy Simulation Workflow",
    horizon_years: workflowHorizonYears.value,
    configuration: {
      ...existingConfiguration,
      periods,
      policies,
      events
    }
  };
  return workflowData.value.configuration;
}

const workflowTimelineItems = computed(() => {
  const periodItems = workflowPeriodRows.value.map((row, index) => ({
    ...row,
    type: "phase",
    row: "phase",
    compact: false,
    order: index,
    laneIndex: index,
    laneCount: workflowPeriodRows.value.length
  }));
  const policyItems = workflowPolicyRows.value.map((row, index) => ({
    ...row,
    type: "policy",
    row: "policy",
    compact: Math.max(1, Number(row.endTick || row.startTick) - Number(row.startTick || 0)) <= 3,
    order: 100 + index,
    laneIndex: index,
    laneCount: workflowPolicyRows.value.length
  }));
  const eventItems = workflowEventRows.value.map((row, index) => ({
    ...row,
    type: "event",
    row: "event",
    endTick: row.startTick,
    compact: true,
    order: 200 + index,
    laneIndex: index,
    laneCount: workflowEventRows.value.length
  }));
  return [...periodItems, ...policyItems, ...eventItems].sort(
    (a, b) => (Number(a.startTick || 0) - Number(b.startTick || 0)) || (a.order - b.order)
  );
});

const workflowPeriodBoundaries = computed(() => {
  const total = Math.max(1, Number(workflowTicks.value || 60));
  const periods = [...workflowPeriodRows.value].sort(
    (a, b) => Number(a.startTick || 0) - Number(b.startTick || 0)
  );
  return periods.slice(0, -1).map((period, index) => {
    const nextPeriod = periods[index + 1];
    const month = Number(period.endTick || nextPeriod.startTick || 0);
    return {
      id: `${period.id}-${nextPeriod.id}`,
      leftId: period.id,
      rightId: nextPeriod.id,
      month,
      percent: clampNumber((month / total) * 100, 0, 100),
      label: `Merge P${index + 1} + P${index + 2}`
    };
  });
});

const workflowTimelineTrackStyle = computed(() => ({
  "--timeline-track-min-width": `${Math.max(860, Number(workflowTicks.value || 60) * 18)}px`
}));

const timelineScaleTicks = computed(() => {
  const total = Math.max(1, Number(workflowTicks.value || 60));
  const step = total <= 36 ? 6 : 12;
  const ticks = [];
  for (let tick = 0; tick <= total; tick += step) {
    ticks.push({
      tick,
      percent: Math.min(100, (tick / total) * 100),
      shift: tick === 0 ? "0" : tick >= total ? "-100%" : "-50%"
    });
  }
  if (!ticks.some((item) => item.tick === total)) {
    ticks.push({ tick: total, percent: 100, shift: "-100%" });
  }
  return ticks;
});

function workflowTimelineItemStyle(item) {
  const total = Math.max(1, Number(workflowTicks.value || 60));
  const start = clampNumber(Number(item.startTick || 0), 0, total);
  const end = item.type === "event"
    ? start
    : clampNumber(Number(item.endTick ?? start + 1), start + 1, total);
  const left = (start / total) * 100;
  const width = item.type === "event" ? 0 : Math.max(4, ((end - start) / total) * 100);
  const laneCount = Math.max(1, Number(item.laneCount || 1));
  const laneIndex = Math.max(0, Number(item.laneIndex || 0));
  const maxLaneSpan = item.type === "policy" ? 174 : 126;
  const preferredGap = item.type === "policy" ? 64 : 68;
  const laneGap = laneCount > 1 ? Math.min(preferredGap, maxLaneSpan / (laneCount - 1)) : 0;
  const laneOffset = (laneIndex - ((laneCount - 1) / 2)) * laneGap;
  const top = item.type === "phase"
    ? "calc(var(--phase-row-top, 60px) + (var(--phase-row-height, 72px) / 2))"
    : item.type === "policy"
      ? `calc(var(--policy-row-top, 132px) + ((var(--policy-row-height, 250px) + var(--timeline-flex-row-extra, 0px)) / 2) + ${laneOffset}px)`
      : `calc(var(--event-row-top, 382px) + var(--timeline-flex-row-extra, 0px) + ((var(--event-row-height, 208px) + var(--timeline-flex-row-extra, 0px)) / 2) + ${laneOffset}px)`;
  return item.type === "event"
    ? { left: `${left}%`, top }
    : { left: `${left}%`, width: `${width}%`, top };
}

function timelineItemIcon(type) {
  if (type === "policy") return Shield;
  if (type === "event") return Target;
  return LineChart;
}

const selectedTimelineItem = computed(() =>
  workflowTimelineItems.value.find((item) => item.id === selectedTimelineItemId.value) || (selectedTimelineItemId.value ? workflowTimelineItems.value[0] : null)
);

const selectedTimelineKindLabel = computed(() => {
  const type = selectedTimelineItem.value?.type;
  if (type === "policy") return "Policy";
  if (type === "event") return "Event";
  return "Period";
});

const selectedTimelineDuration = computed(() => {
  const item = selectedTimelineItem.value;
  if (!item || item.type === "event") return 0;
  return Math.max(1, Math.round(Number(item.endTick || 0) - Number(item.startTick || 0)));
});

const selectedTimelinePeriodIndex = computed(() => {
  const item = selectedTimelineItem.value;
  if (!item || item.type !== "phase") return -1;
  return workflowPeriodRows.value.findIndex((period) => period.id === item.id);
});

const canRemoveSelectedTimelineItem = computed(() => {
  const item = selectedTimelineItem.value;
  if (!item) return false;
  if (item.type === "phase") return false;
  return true;
});

const workflowWarningsCount = computed(() => {
  let count = 0;
  if (!workflowPeriodRows.value.length) count += 1;
  if (!workflowPolicyRows.value.length) count += 1;
  if (!workflowEventRows.value.length) count += 1;
  if (!useDatabaseAgents.value && usePriorNetworkEdges.value) count += 1;
  return count;
});

const workflowWarningAnchorId = computed(() =>
  workflowPolicyRows.value[0]?.id || workflowEventRows.value[0]?.id || workflowPeriodRows.value[0]?.id || "baseline"
);

const workflowReadinessLabel = computed(() => {
  if (workflowRunStatus.value === "created") return "Created";
  if (workflowRunStatus.value === "running") return "Running";
  if (workflowRunStatus.value === "completed") return "Completed";
  if (workflowRunStatus.value === "failed") return "Failed";
  return workflowWarningsCount.value ? "Review" : "Ready";
});

const workflowEstimatedRuntimeMinutes = computed(() => {
  const agents = Math.max(1, Number(displayedSimulationAgentCount.value || simulationAgentCount.value || 1));
  const ticks = Math.max(1, Number(workflowTicks.value || 60));
  return Math.max(1, Math.round((agents / 180) + (ticks / 42)));
});

function selectTimelineItem(id) {
  ensureWorkflowConfiguration();
  selectedTimelineItemId.value = id || workflowWarningAnchorId.value;
  workflowInspectorOpen.value = true;
}

let suppressWorkflowTimelineClick = false;

function workflowMonthFromClientX(clientX) {
  const track = workflowTimelineTrack.value;
  if (!track) return 0;
  const rect = track.getBoundingClientRect();
  if (!rect.width) return 0;
  const relativeX = clampNumber(Number(clientX || 0) - rect.left, 0, rect.width);
  return Math.round((relativeX / rect.width) * Math.max(1, Number(workflowTicks.value || 60)));
}

function updateWorkflowPeriodSplitPreview(event, item) {
  if (!item || item.type !== "phase" || workflowTimelineDragState.value) return;
  if (event.target?.closest?.(".timeline-resize-handle")) {
    clearWorkflowPeriodSplitPreview(item.id);
    return;
  }
  const month = workflowMonthFromClientX(event.clientX);
  const start = Number(item.startTick || 0);
  const end = Number(item.endTick || start + 1);
  workflowPeriodHoverState.value = month > start && month < end
    ? { id: item.id, month }
    : null;
}

function clearWorkflowPeriodSplitPreview(id = "") {
  if (!id || workflowPeriodHoverState.value?.id === id) workflowPeriodHoverState.value = null;
}

function workflowPeriodSplitPreviewStyle(item) {
  const hover = workflowPeriodHoverState.value;
  const start = Number(item?.startTick || 0);
  const end = Number(item?.endTick || start + 1);
  if (!hover || hover.id !== item?.id || end <= start) return { left: "50%" };
  return { left: `${clampNumber(((hover.month - start) / (end - start)) * 100, 0, 100)}%` };
}

function handleWorkflowTimelineItemClick(event, item) {
  if (suppressWorkflowTimelineClick) return;
  if (item?.type !== "phase") {
    selectTimelineItem(item?.id);
    return;
  }
  if (event?.detail === 0) {
    selectTimelineItem(item.id);
    return;
  }
  const splitMonth = workflowPeriodHoverState.value?.id === item.id
    ? workflowPeriodHoverState.value.month
    : workflowMonthFromClientX(event?.clientX);
  splitWorkflowPeriodAt(item.id, splitMonth);
}

function startWorkflowTimelineDrag(event, item, mode = "move") {
  if (!item || mode === "select") return;
  if (typeof event.button === "number" && event.button !== 0) return;

  const configuration = ensureWorkflowConfiguration();
  const row = findWorkflowConfigRow(item.id);
  if (!row) return;

  event.preventDefault();
  const periodRows = [...(configuration.periods || [])].sort(
    (a, b) => Number(a.startTick || 0) - Number(b.startTick || 0)
  );
  const periodIndex = item.type === "phase" ? periodRows.findIndex((period) => period.id === item.id) : -1;
  const previousPeriod = periodIndex > 0 ? periodRows[periodIndex - 1] : null;
  const nextPeriod = periodIndex >= 0 && periodIndex < periodRows.length - 1 ? periodRows[periodIndex + 1] : null;

  workflowTimelineDragState.value = {
    id: item.id,
    type: item.type,
    mode,
    pointerId: event.pointerId,
    pointerMonth: workflowMonthFromClientX(event.clientX),
    lastMonth: workflowMonthFromClientX(event.clientX),
    startTick: Number(row.startTick || 0),
    endTick: Number(row.endTick ?? row.startTick ?? 0),
    row,
    previousPeriod,
    nextPeriod,
    moved: false
  };
  document.documentElement.classList.add("workflow-timeline-dragging");
  window.addEventListener("pointermove", handleWorkflowTimelinePointerMove, { passive: false });
  window.addEventListener("pointerup", finishWorkflowTimelineDrag);
  window.addEventListener("pointercancel", finishWorkflowTimelineDrag);
}

function handleWorkflowTimelinePointerMove(event) {
  const drag = workflowTimelineDragState.value;
  if (!drag || (drag.pointerId != null && event.pointerId !== drag.pointerId)) return;
  event.preventDefault();

  const total = Math.max(1, Number(workflowTicks.value || 60));
  const currentMonth = workflowMonthFromClientX(event.clientX);
  if (currentMonth === drag.lastMonth) return;
  drag.lastMonth = currentMonth;
  drag.moved = true;
  suppressWorkflowTimelineClick = true;

  if (drag.type === "phase") {
    if (drag.mode === "resize-start" && drag.previousPeriod) {
      const boundary = clampNumber(
        currentMonth,
        Number(drag.previousPeriod.startTick || 0) + 1,
        Number(drag.row.endTick || total) - 1
      );
      drag.previousPeriod.endTick = boundary;
      drag.row.startTick = boundary;
      normalizeWorkflowConfigRow(drag.previousPeriod);
      normalizeWorkflowConfigRow(drag.row);
    } else if (drag.mode === "resize-end" && drag.nextPeriod) {
      const boundary = clampNumber(
        currentMonth,
        Number(drag.row.startTick || 0) + 1,
        Number(drag.nextPeriod.endTick || total) - 1
      );
      drag.row.endTick = boundary;
      drag.nextPeriod.startTick = boundary;
      normalizeWorkflowConfigRow(drag.row);
      normalizeWorkflowConfigRow(drag.nextPeriod);
    }
  } else if (drag.type === "event") {
    const nextStart = clampNumber(drag.startTick + currentMonth - drag.pointerMonth, 0, total);
    drag.row.startTick = nextStart;
    drag.row.endTick = nextStart;
  } else if (drag.mode === "move") {
    const duration = Math.max(1, drag.endTick - drag.startTick);
    const nextStart = clampNumber(drag.startTick + currentMonth - drag.pointerMonth, 0, total - duration);
    drag.row.startTick = nextStart;
    drag.row.endTick = nextStart + duration;
  } else if (drag.mode === "resize-start") {
    drag.row.startTick = clampNumber(currentMonth, 0, Number(drag.row.endTick || total) - 1);
  } else if (drag.mode === "resize-end") {
    drag.row.endTick = clampNumber(currentMonth, Number(drag.row.startTick || 0) + 1, total);
  }

  normalizeWorkflowConfigRow(drag.row);
  workflowTemplateMessage.value = "";
}

function finishWorkflowTimelineDrag(event) {
  const drag = workflowTimelineDragState.value;
  if (drag && drag.pointerId != null && event?.pointerId != null && event.pointerId !== drag.pointerId) return;
  const moved = Boolean(drag?.moved);
  workflowTimelineDragState.value = null;
  document.documentElement.classList.remove("workflow-timeline-dragging");
  window.removeEventListener("pointermove", handleWorkflowTimelinePointerMove);
  window.removeEventListener("pointerup", finishWorkflowTimelineDrag);
  window.removeEventListener("pointercancel", finishWorkflowTimelineDrag);
  if (moved) window.setTimeout(() => { suppressWorkflowTimelineClick = false; }, 0);
}

function addWorkflowTimelineItem(type = "event") {
  const configuration = ensureWorkflowConfiguration();
  const total = Math.max(12, Number(workflowTicks.value || 60));
  const id = `${type}-${Date.now().toString(36)}`;

  if (type === "phase") {
    const startTick = Math.max(0, Math.round(total * 0.72));
    configuration.periods.push({
      id,
      title: `New Period ${configuration.periods.length + 1}`,
      type: "phase",
      stage: "custom",
      startTick,
      endTick: total,
      note: "Custom analysis period."
    });
  } else if (type === "policy") {
    const startTick = Math.round(total * 0.42);
    configuration.policies.push({
      id,
      title: `Policy Intervention ${configuration.policies.length + 1}`,
      type: "policy",
      startTick,
      endTick: Math.min(total, startTick + Math.max(6, Math.round(total * 0.22))),
      note: "Policy span added from workflow configuration."
    });
  } else {
    const startTick = Math.round(total * 0.62);
    configuration.events.push({
      id,
      title: `External Event ${configuration.events.length + 1}`,
      type: "event",
      startTick,
      endTick: startTick,
      note: "External change event added from workflow configuration."
    });
  }

  selectedTimelineItemId.value = id;
  workflowTemplateMessage.value = "";
}

function sortWorkflowPeriods(configuration) {
  const periods = Array.isArray(configuration?.periods) ? configuration.periods : [];
  periods.forEach((period) => {
    period.type = "phase";
    normalizeWorkflowConfigRow(period);
  });
  periods.sort((a, b) => Number(a.startTick || 0) - Number(b.startTick || 0));
  configuration.periods = periods;
  return periods;
}

function splitWorkflowPeriodAt(periodId, requestedMonth) {
  const configuration = ensureWorkflowConfiguration();
  const periods = sortWorkflowPeriods(configuration);
  const periodIndex = periods.findIndex((period) => period.id === periodId);
  if (periodIndex < 0) return;

  const period = periods[periodIndex];
  const splitMonth = Math.round(Number(requestedMonth));
  const originalStart = Number(period.startTick || 0);
  const originalEnd = Number(period.endTick || splitMonth + 1);
  if (!Number.isFinite(splitMonth) || splitMonth <= originalStart || splitMonth >= originalEnd) return;
  const newPeriodId = `period-${Date.now().toString(36)}-${periods.length + 1}`;
  const newPeriod = {
    ...period,
    id: newPeriodId,
    title: `${String(period.title || `Period ${periodIndex + 1}`).replace(/\s+- Part \d+$/, "")} - Part 2`,
    shortTitle: undefined,
    startTick: splitMonth,
    endTick: originalEnd,
    tone: ["blue", "green", "orange", "purple"][(periodIndex + 1) % 4],
    note: period.note || "Split from an existing simulation period."
  };

  period.endTick = splitMonth;
  normalizeWorkflowConfigRow(period);
  normalizeWorkflowConfigRow(newPeriod);
  periods.splice(periodIndex + 1, 0, newPeriod);
  configuration.periods = periods;
  workflowPeriodHoverState.value = null;
  if (selectedTimelineItemId.value === periodId) selectedTimelineItemId.value = "";
  workflowTemplateMessageTone.value = "success";
  workflowTemplateMessage.value = `Period split at Month ${splitMonth}.`;
}

function mergeWorkflowPeriodBoundary(boundary) {
  if (!boundary?.leftId || !boundary?.rightId) return;
  const configuration = ensureWorkflowConfiguration();
  const periods = sortWorkflowPeriods(configuration);
  const firstIndex = periods.findIndex((period) => period.id === boundary.leftId);
  const secondIndex = periods.findIndex((period) => period.id === boundary.rightId);
  if (firstIndex < 0 || secondIndex !== firstIndex + 1) return;
  const firstPeriod = periods[firstIndex];
  const secondPeriod = periods[secondIndex];
  const firstBaseTitle = String(firstPeriod.title || `Period ${firstIndex + 1}`).replace(/\s+- Part \d+$/, "");
  const secondBaseTitle = String(secondPeriod.title || `Period ${secondIndex + 1}`).replace(/\s+- Part \d+$/, "");
  const notes = [...new Set([firstPeriod.note, secondPeriod.note].filter(Boolean))];

  firstPeriod.startTick = Math.min(Number(firstPeriod.startTick || 0), Number(secondPeriod.startTick || 0));
  firstPeriod.endTick = Math.max(Number(firstPeriod.endTick || 0), Number(secondPeriod.endTick || 0));
  firstPeriod.title = firstBaseTitle === secondBaseTitle
    ? firstBaseTitle
    : `${formatPeriodShortTitle(firstBaseTitle).replace(/\.\.\.$/, "")} + ${formatPeriodShortTitle(secondBaseTitle).replace(/\.\.\.$/, "")}`;
  firstPeriod.shortTitle = undefined;
  firstPeriod.stage = firstPeriod.stage === secondPeriod.stage ? firstPeriod.stage : "combined";
  firstPeriod.note = notes.join("\n");
  normalizeWorkflowConfigRow(firstPeriod);

  periods.splice(secondIndex, 1);
  configuration.periods = periods;
  workflowPeriodHoverState.value = null;
  if ([firstPeriod.id, secondPeriod.id].includes(selectedTimelineItemId.value)) selectedTimelineItemId.value = "";
  workflowTemplateMessageTone.value = "success";
  workflowTemplateMessage.value = `P${firstIndex + 1} and P${secondIndex + 1} merged into one continuous period.`;
}

function removeSelectedWorkflowTimelineItem() {
  const item = selectedTimelineItem.value;
  if (!item || !canRemoveSelectedTimelineItem.value) return;
  const configuration = ensureWorkflowConfiguration();
  const collectionKey = item.type === "phase" ? "periods" : item.type === "policy" ? "policies" : "events";
  configuration[collectionKey] = configuration[collectionKey].filter((row) => row.id !== item.id);
  selectedTimelineItemId.value = workflowTimelineItems.value.find((row) => row.id !== item.id)?.id || "";
  workflowTemplateMessage.value = "";
}

function workflowCollectionKeyForType(type) {
  if (type === "phase") return "periods";
  if (type === "policy") return "policies";
  return "events";
}

function normalizeWorkflowConfigRow(row) {
  if (!row) return;
  const total = Math.max(1, Number(workflowTicks.value || 60));
  row.startTick = clampNumber(Number(row.startTick ?? row.start_tick ?? row.tick ?? 0), 0, total);
  if (row.type === "event") {
    row.endTick = row.startTick;
  } else {
    row.endTick = clampNumber(Number(row.endTick ?? row.end_tick ?? row.end ?? row.startTick + 1), row.startTick + 1, total);
  }
  if (!row.title?.trim?.()) row.title = row.type === "policy" ? "Policy Intervention" : row.type === "event" ? "External Event" : "Simulation Period";
}

function findWorkflowConfigRow(id) {
  const configuration = ensureWorkflowConfiguration();
  const collections = ["periods", "policies", "events"];
  for (const key of collections) {
    const row = configuration[key]?.find((item) => item.id === id);
    if (row) {
      row.type = row.type || (key === "periods" ? "phase" : key === "policies" ? "policy" : "event");
      return row;
    }
  }
  return null;
}

function updateSelectedTimelineItem(patch = {}) {
  const selected = selectedTimelineItem.value;
  if (!selected) return;
  const row = findWorkflowConfigRow(selected.id);
  if (!row) return;

  if (selected.type === "phase") {
    const configuration = ensureWorkflowConfiguration();
    const periods = sortWorkflowPeriods(configuration);
    const periodIndex = periods.findIndex((period) => period.id === selected.id);
    const previousPeriod = periodIndex > 0 ? periods[periodIndex - 1] : null;
    const nextPeriod = periodIndex >= 0 && periodIndex < periods.length - 1 ? periods[periodIndex + 1] : null;
    const contentPatch = { ...patch };
    delete contentPatch.startTick;
    delete contentPatch.endTick;
    Object.assign(row, contentPatch);

    if (Object.prototype.hasOwnProperty.call(patch, "startTick") && previousPeriod) {
      const boundary = clampNumber(
        Math.round(Number(patch.startTick)),
        Number(previousPeriod.startTick || 0) + 1,
        Number(row.endTick || 1) - 1
      );
      previousPeriod.endTick = boundary;
      row.startTick = boundary;
      normalizeWorkflowConfigRow(previousPeriod);
    }
    if (Object.prototype.hasOwnProperty.call(patch, "endTick") && nextPeriod) {
      const boundary = clampNumber(
        Math.round(Number(patch.endTick)),
        Number(row.startTick || 0) + 1,
        Number(nextPeriod.endTick || workflowTicks.value) - 1
      );
      row.endTick = boundary;
      nextPeriod.startTick = boundary;
      normalizeWorkflowConfigRow(nextPeriod);
    }
    if (Object.prototype.hasOwnProperty.call(patch, "title")) row.shortTitle = undefined;
  } else {
    Object.assign(row, patch);
  }
  normalizeWorkflowConfigRow(row);
  workflowTemplateMessage.value = "";
}

function confirmSelectedTimelineItemUpdate() {
  ensureWorkflowConfiguration();
  workflowTemplateMessageTone.value = "success";
  workflowTemplateMessage.value = "Workflow item updated.";
}

async function saveWorkflowTemplate() {
  try {
    const id = workflowData.value?.workflow_id || "WF001";
    workflowData.value = await workflowApi.update(id, buildWorkflowConfigurationPayload());
    await workflowApi.saveTemplate(id);
    workflowTemplateMessageTone.value = "success";
    workflowTemplateMessage.value = "Template saved, including procurement mode (until backend restart).";
  } catch (error) {
    workflowTemplateMessageTone.value = "error";
    workflowTemplateMessage.value = error.message || "Could not save the template.";
  }
}

async function loadWorkflowTemplate() {
  try {
    const template = await workflowApi.loadTemplate();
    workflowData.value = template;
    workflowTicks.value = Number(template.execution_logic?.total_ticks || template.horizon_years * 12);
    const configuration = template.configuration || {};
    useDatabaseAgents.value = configuration.agent_source !== "default";
    simulationAgentCount.value = Number(configuration.agent_count || 1000);
    maxTenderInvites.value = Number(configuration.max_tender_invites || 40);
    usePriorNetworkEdges.value = configuration.use_prior_network_edges ?? true;
    workflowTemplateMessageTone.value = "success";
    workflowTemplateMessage.value = "Saved template loaded. Existing simulations keep their original mode.";
  } catch (error) {
    workflowTemplateMessageTone.value = "error";
    workflowTemplateMessage.value = error.message || "Could not load the template.";
  }
}

const periodAnalysisPeriods = computed(() => workflowPeriodRows.value.map((period, index) => {
  const startTick = Number(period.startTick || 0);
  const endTick = Number(period.endTick || startTick + 1);
  const isLastPeriod = index === workflowPeriodRows.value.length - 1;
  const policyCount = workflowPolicyRows.value.filter((policy) =>
    Number(policy.startTick || 0) < endTick && Number(policy.endTick || policy.startTick || 0) > startTick
  ).length;
  const eventCount = workflowEventRows.value.filter((event) => {
    const eventMonth = Number(event.startTick || 0);
    return eventMonth >= startTick && (eventMonth < endTick || (isLastPeriod && eventMonth === endTick));
  }).length;
  const exposureCount = policyCount + eventCount;
  return {
    ...period,
    index: period.index || index + 1,
    shortTitle: period.shortTitle || formatPeriodShortTitle(period.title),
    range: period.range || timelineMonthRangeLabel(period),
    duration: Math.max(1, Number(period.duration || period.endTick - period.startTick || 1)),
    policyCount,
    events: eventCount,
    eventCount,
    exposure: period.exposure || (exposureCount > 1 ? "Medium" : "Low"),
    exposureTone: period.exposureTone || (exposureCount > 1 ? "medium" : "low")
  };
}));

const periodMetricDefinitions = [
  { key: "collaboration", label: "Collaboration", icon: Network, tone: "blue", color: "#2f6fdd" },
  { key: "resource", label: "Resource Flow", icon: LineChart, tone: "green", color: "#0a9d62" },
  { key: "risk", label: "Risk Control", icon: Shield, tone: "purple", color: "#8b5cf6" },
  { key: "regional", label: "Regional Balance", icon: PieChart, tone: "orange", color: "#ff7a16" },
  { key: "lifecycle", label: "Lifecycle Momentum", icon: Timer, tone: "green", color: "#37a66a" }
];

function periodMetricScore(period, index, metricKey) {
  const start = Math.max(0, Math.round(Number(period.startTick ?? period.start ?? 0)));
  const end = Math.max(start, Math.round(Number(
    period.endTick ?? period.end ?? start + Number(period.duration || 1)
  )));
  const actualValues = [];
  for (let month = start; month <= end; month += 1) {
    const value = readPeriodEvolutionActualScore(month, metricKey);
    if (Number.isFinite(value)) actualValues.push(value);
  }
  if (actualValues.length) {
    const average = actualValues.reduce((sum, value) => sum + value, 0) / actualValues.length;
    return Math.round(metricKey === "risk" ? 100 - average : average);
  }

  const policyCount = Number(period.policyCount || 0);
  const eventCount = Number(period.events || period.eventCount || 0);
  const duration = Math.max(1, Number(period.duration || 1));
  const baseByMetric = {
    collaboration: 58 + index * 8 + policyCount * 5 - eventCount * 4,
    resource: 60 + index * 5 + policyCount * 3 - eventCount * 5,
    risk: 68 + policyCount * 3 - eventCount * 8 + index * 2,
    regional: 56 + index * 6 + Math.min(duration, 24) * 0.35,
    lifecycle: 62 + index * 7 + policyCount * 4 - eventCount * 3
  };
  return Math.round(clampNumber(baseByMetric[metricKey] ?? 60, 18, 96));
}

function periodDimensionLabel(period, index, mode = "strongest") {
  const scores = periodMetricDefinitions.map((metric) => ({
    label: metric.label,
    score: periodMetricScore(period, index, metric.key)
  }));
  const sorted = scores.sort((a, b) => mode === "weakest" ? a.score - b.score : b.score - a.score);
  return sorted[0]?.label || "N/A";
}

const periodMatrixGridStyle = computed(() => ({
  gridTemplateColumns: `minmax(150px, .92fr) repeat(${Math.max(1, periodAnalysisPeriods.value.length)}, minmax(92px, 1fr)) minmax(72px, .42fr)`
}));

const periodMatrixScoreDomain = computed(() => {
  const scores = periodMetricDefinitions.flatMap((metric) =>
    periodAnalysisPeriods.value.map((period, index) => periodMetricScore(period, index, metric.key))
  );
  if (!scores.length) return { min: 0, max: 100 };

  const observedMin = Math.min(...scores);
  const observedMax = Math.max(...scores);
  const observedRange = Math.max(1, observedMax - observedMin);
  const padding = Math.max(2, Math.ceil(observedRange * 0.12));
  let min = Math.max(0, Math.floor((observedMin - padding) / 5) * 5);
  let max = Math.min(100, Math.ceil((observedMax + padding) / 5) * 5);

  if (max - min < 10) {
    const midpoint = (min + max) / 2;
    min = Math.max(0, Math.floor((midpoint - 5) / 5) * 5);
    max = Math.min(100, Math.ceil((midpoint + 5) / 5) * 5);
  }
  return { min, max };
});

const periodAnalysisMatrixRows = computed(() => periodMetricDefinitions.map((metric) => {
  const rawCells = periodAnalysisPeriods.value.map((period, index) => {
    const score = periodMetricScore(period, index, metric.key);
    return {
      period: period.id || index,
      score
    };
  });
  const highestScore = rawCells.length ? Math.max(...rawCells.map((cell) => cell.score)) : 0;
  const cells = rawCells.map((cell) => {
    const domain = periodMatrixScoreDomain.value;
    const normalizedScore = clampNumber(
      ((cell.score - domain.min) / Math.max(1, domain.max - domain.min)) * 100,
      0,
      100
    );
    const heatHue = normalizedScore <= 50
      ? 10 + normalizedScore * 0.72
      : 46 + (normalizedScore - 50) * 1.56;
    const heatSaturation = 54 - normalizedScore * 0.18;
    const heatLightness = 91 - normalizedScore * 0.28;
    return {
      ...cell,
      isBest: cell.score === highestScore,
      heatStyle: {
        background: `linear-gradient(135deg, hsl(${heatHue} ${heatSaturation}% ${Math.min(96, heatLightness + 5)}%) 0%, hsl(${heatHue} ${heatSaturation}% ${heatLightness}%) 100%)`,
        borderColor: `hsl(${heatHue} ${Math.max(28, heatSaturation - 12)}% ${Math.max(48, heatLightness - 9)}%)`,
        color: normalizedScore >= 94 ? "#ffffff" : "#253044"
      }
    };
  });
  const bestCell = cells.reduce((best, cell, index) =>
    cell.score > best.score ? { ...cell, index } : best,
  { ...cells[0], index: 0 });
  return {
    ...metric,
    cells,
    best: cells.length ? `P${periodAnalysisPeriods.value[bestCell.index]?.index || bestCell.index + 1}` : "N/A",
    bestTone: metric.tone
  };
}));

function periodTransitionMetrics(fromPeriod, toPeriod, fromIndex, toIndex) {
  return [
    { key: "collaboration", label: "Collaboration", icon: Network },
    { key: "resource", label: "Resource Flow", icon: LineChart },
    { key: "risk", label: "Risk Control", icon: Shield }
  ].map((metric) => {
    const delta = periodMetricScore(toPeriod, toIndex, metric.key) - periodMetricScore(fromPeriod, fromIndex, metric.key);
    return {
      ...metric,
      value: `${delta >= 0 ? "+" : ""}${delta}`,
      delta,
      positive: delta >= 0
    };
  });
}

const periodTransitionSummaries = computed(() => periodAnalysisPeriods.value.slice(0, -1).map((period, index) => {
  const nextPeriod = periodAnalysisPeriods.value[index + 1];
  const metrics = periodTransitionMetrics(period, nextPeriod, index, index + 1);
  const net = metrics.reduce((sum, metric) => sum + metric.delta, 0);
  return {
    label: `P${period.index} -> P${nextPeriod.index}`,
    badge: net >= 0 ? "Improving transition" : "Pressure transition",
    metrics
  };
}));

const periodTransitionRanking = computed(() => {
  const periods = periodAnalysisPeriods.value;
  const fromIndex = Math.round(clampNumber(periodFocusedTransitionIndex.value, 0, Math.max(0, periods.length - 2)));
  const from = periods[fromIndex] || periods[0];
  const to = periods[fromIndex + 1] || periods[fromIndex] || from;
  if (!from || !to) return [];
  const rows = periodMetricDefinitions.map((metric) => {
    const fromScore = periodMetricScore(from, fromIndex, metric.key);
    const toScore = periodMetricScore(to, fromIndex + 1, metric.key);
    return {
      ...metric,
      title: metric.label,
      fromScore,
      toScore,
      fromPeriod: from.index,
      toPeriod: to.index,
      delta: toScore - fromScore
    };
  });
  const positiveTotal = rows.reduce((sum, row) => sum + Math.max(0, row.delta), 0);
  return rows
    .sort((a, b) => b.delta - a.delta)
    .map((row, index) => ({
      ...row,
      rank: index + 1,
      value: `${row.delta >= 0 ? "+" : ""}${row.delta}`,
      negative: row.delta < 0,
      contribution: positiveTotal > 0 ? Math.round((Math.max(0, row.delta) / positiveTotal) * 100) : 0
    }));
});

const periodFocusedTransition = computed(() => {
  const periods = periodAnalysisPeriods.value;
  const fromIndex = Math.round(clampNumber(periodFocusedTransitionIndex.value, 0, Math.max(0, periods.length - 2)));
  const from = periods[fromIndex] || periods[0] || {
    index: 1,
    title: "Baseline",
    shortTitle: "Baseline",
    range: "Month 0 - Month 24",
    duration: 24,
    stage: "Baseline"
  };
  const to = periods[fromIndex + 1] || periods[fromIndex] || from;
  const metrics = periodTransitionMetrics(from, to, fromIndex, fromIndex + 1);
  const deltas = metrics.map((metric) => ({
    label: metric.label,
    value: metric.value,
    detail: metric.positive ? "Improves in the next period." : "Declines in the next period.",
    negative: !metric.positive
  }));
  const net = metrics.reduce((sum, metric) => sum + metric.delta, 0);
  return {
    label: `P${from.index} -> P${to.index}`,
    from,
    to,
    deltas,
    takeaway: net >= 0
      ? "The selected transition shows a net improvement, led by collaboration and lifecycle momentum."
      : "The selected transition shows pressure and should be checked against risk triggers."
  };
});

const periodEvolutionBands = computed(() => {
  const periods = periodAnalysisPeriods.value;
  const totalDuration = periods.reduce((sum, period) => sum + Number(period.duration || 1), 0) || 1;
  let cursor = 20;
  return periods.map((period, index) => {
    const width = Math.max(18, (Number(period.duration || 1) / totalDuration) * 228);
    const band = {
      label: period.shortTitle,
      x: cursor,
      width,
      tone: index % 4 === 0 ? "blue" : index % 4 === 1 ? "green" : index % 4 === 2 ? "orange" : "purple"
    };
    cursor += width;
    return band;
  });
});

const periodEvolutionPoints = computed(() => {
  const periods = periodAnalysisPeriods.value;
  if (!periods.length) return "20,96 248,64";
  const denominator = Math.max(1, periods.length - 1);
  return periods.map((period, index) => {
    const x = 22 + (index / denominator) * 224;
    const y = 136 - periodMetricScore(period, index, "collaboration") * 1.02;
    return `${x.toFixed(1)},${clampNumber(y, 24, 136).toFixed(1)}`;
  }).join(" ");
});

const periodEvolutionMetrics = [
  { key: "project", label: "Project Output", color: "#4b74e8" },
  { key: "collaboration", label: "Collaboration", color: "#2f6fdd" },
  { key: "resource", label: "Resource Flow", color: "#2fa36b" },
  { key: "lifecycle", label: "Lifecycle Efficiency", color: "#ff9b3d" },
  { key: "regional", label: "Regional Balance", color: "#8b5cf6" },
  { key: "risk", label: "Risk Exposure (-)", color: "#ef4444" }
];

const periodEvolutionChartBounds = {
  left: 46,
  right: 600,
  top: 22,
  bottom: 186
};

const periodEvolutionMaxMonth = computed(() => {
  const periods = periodAnalysisPeriods.value;
  const maxEnd = Math.max(...periods.map((period) => Number(period.endTick ?? period.end ?? 0)), 0);
  if (maxEnd > 0) return Math.max(12, maxEnd);
  return Math.max(12, periods.reduce((sum, period) => sum + Number(period.duration || 0), 0) || 60);
});

function periodEvolutionX(month) {
  const maxMonth = Math.max(1, periodEvolutionMaxMonth.value);
  const { left, right } = periodEvolutionChartBounds;
  return left + (clampNumber(month, 0, maxMonth) / maxMonth) * (right - left);
}

function periodEvolutionY(value) {
  const { top, bottom } = periodEvolutionChartBounds;
  return bottom - (clampNumber(value, 0, 100) / 100) * (bottom - top);
}

function periodEvolutionFallbackScore(month, metricKey) {
  const maxMonth = Math.max(1, periodEvolutionMaxMonth.value);
  const progress = clampNumber(month / maxMonth, 0, 1);
  const periodIndex = Math.max(0, periodAnalysisPeriods.value.findIndex((period) => {
    const start = Number(period.startTick ?? period.start ?? 0);
    const end = Number(period.endTick ?? start + Number(period.duration || 1));
    return month >= start && month <= end;
  }));
  const wave = Math.sin(month / 5.6) * 2.2;
  const phaseLift = periodIndex * 2.5;
  const scores = {
    project: 14 + progress * 70 + phaseLift + wave,
    collaboration: 12 + progress * 72 + phaseLift + Math.sin(month / 4.8) * 2,
    resource: 18 + progress * 62 + phaseLift + Math.sin(month / 6.2) * 1.8,
    lifecycle: 16 + progress * 66 + phaseLift + Math.sin(month / 5.1) * 2.1,
    regional: 19 + progress * 52 + periodIndex * 3 + Math.sin(month / 7.5) * 1.5,
    risk: 86 - progress * 24 - periodIndex * 2.6 + Math.sin(month / 8) * 1.7
  };
  return Math.round(clampNumber(scores[metricKey] ?? 50, 0, 100));
}

function readPeriodEvolutionActualScore(month, metricKey) {
  const point = playbackTimeline.value.find((row) =>
    Number(row.tick ?? row.month ?? row.time ?? -1) === Number(month)
  );
  if (!point) return null;
  const source = point.metrics || point.kpis || point;
  const candidates = {
    project: ["project_output", "projectOutput", "active_projects_score", "project_score", "progress"],
    collaboration: ["collaboration_index", "collaboration", "network_density_score", "cross_region_score"],
    resource: ["resource_flow_index", "resource_flow", "resourceFlow", "flow_score"],
    lifecycle: ["lifecycle_efficiency", "lifecycle", "lifecycle_progress", "progress_score"],
    regional: ["regional_balance", "regionalBalance", "balance_score"],
    risk: ["risk_exposure", "riskExposure", "risk_score", "failure_risk"]
  }[metricKey] || [];
  for (const key of candidates) {
    const raw = Number(source?.[key]);
    if (Number.isFinite(raw)) {
      if (raw >= 0 && raw <= 1) return Math.round(raw * 100);
      if (raw >= 0 && raw <= 100) return Math.round(raw);
    }
  }
  return null;
}

function periodEvolutionScore(month, metricKey) {
  return readPeriodEvolutionActualScore(month, metricKey) ?? periodEvolutionFallbackScore(month, metricKey);
}

const periodEvolutionMonths = computed(() =>
  Array.from({ length: periodEvolutionMaxMonth.value + 1 }, (_, month) => month)
);

const periodEvolutionXTicks = computed(() => {
  const maxMonth = periodEvolutionMaxMonth.value;
  const ticks = [];
  for (let month = 0; month <= maxMonth; month += 12) ticks.push(month);
  if (!ticks.includes(maxMonth)) ticks.push(maxMonth);
  return ticks.map((month, index) => ({
    month,
    label: `Month ${month}`,
    x: periodEvolutionX(month),
    anchor: index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle",
    boundary: periodAnalysisPeriods.value.some((period) => Number(period.startTick ?? period.start ?? -1) === month && month !== 0),
    tone: periodAnalysisPeriods.value[index % Math.max(1, periodAnalysisPeriods.value.length)]?.exposureTone || "green"
  }));
});

const periodEvolutionYTicks = computed(() => [100, 75, 50, 25, 0].map((value) => ({
  value,
  y: periodEvolutionY(value)
})));

const periodEvolutionChartBands = computed(() => periodAnalysisPeriods.value.map((period, index) => {
  const start = Number(period.startTick ?? period.start ?? 0);
  const end = Number(period.endTick ?? start + Number(period.duration || 1));
  const x = periodEvolutionX(start);
  return {
    label: period.shortTitle,
    x,
    width: Math.max(8, periodEvolutionX(end) - x),
    tone: index % 4 === 0 ? "blue" : index % 4 === 1 ? "green" : index % 4 === 2 ? "orange" : "purple"
  };
}));

const periodEvolutionPeriodLabels = computed(() => periodAnalysisPeriods.value.map((period, index) => {
  const start = Number(period.startTick ?? period.start ?? 0);
  const end = Number(period.endTick ?? start + Number(period.duration || 1));
  return {
    key: period.id || index,
    index: period.index || index + 1,
    title: period.shortTitle,
    x: periodEvolutionX((start + end) / 2),
    tone: index % 4 === 0 ? "blue" : index % 4 === 1 ? "green" : index % 4 === 2 ? "orange" : "purple"
  };
}));

const periodEvolutionSeries = computed(() => periodEvolutionMetrics.map((metric) => ({
  ...metric,
  points: periodEvolutionMonths.value.map((month) =>
    `${periodEvolutionX(month).toFixed(1)},${periodEvolutionY(periodEvolutionScore(month, metric.key)).toFixed(1)}`
  ).join(" ")
})));

function formatPeriodDelta(value, digits = 0) {
  const numeric = Number(value || 0);
  return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(digits)}`;
}

const periodDetailedAnalysis = computed(() => {
  const periods = periodAnalysisPeriods.value;
  const fromIndex = Math.round(clampNumber(
    periodFocusedTransitionIndex.value,
    0,
    Math.max(0, periods.length - 2)
  ));
  const from = periods[fromIndex] || periodFocusedTransition.value.from;
  const to = periods[fromIndex + 1] || periodFocusedTransition.value.to;
  const metricRows = periodMetricDefinitions.map((metric) => {
    const fromScore = periodMetricScore(from, fromIndex, metric.key);
    const toScore = periodMetricScore(to, fromIndex + 1, metric.key);
    return {
      ...metric,
      fromScore,
      toScore,
      delta: toScore - fromScore
    };
  });
  const positiveRows = metricRows.filter((metric) => metric.delta > 0);
  const positiveTotal = positiveRows.reduce((sum, metric) => sum + metric.delta, 0);
  const averageFrom = metricRows.reduce((sum, metric) => sum + metric.fromScore, 0) / Math.max(1, metricRows.length);
  const averageTo = metricRows.reduce((sum, metric) => sum + metric.toScore, 0) / Math.max(1, metricRows.length);
  const averageDelta = averageTo - averageFrom;
  const ranked = [...metricRows].sort((a, b) => b.delta - a.delta);
  const leading = ranked[0] || metricRows[0];
  const lagging = ranked[ranked.length - 1] || metricRows[0];
  const collaboration = metricRows.find((metric) => metric.key === "collaboration") || leading;
  const resource = metricRows.find((metric) => metric.key === "resource") || leading;
  const risk = metricRows.find((metric) => metric.key === "risk") || lagging;
  const regional = metricRows.find((metric) => metric.key === "regional") || leading;
  const lifecycle = metricRows.find((metric) => metric.key === "lifecycle") || leading;
  const conversionRate = collaboration.delta > 0
    ? Math.round(clampNumber((resource.delta / collaboration.delta) * 100, 0, 100))
    : resource.delta > 0 ? 100 : 0;
  const conversionGap = collaboration.delta - resource.delta;

  const startMonth = Math.max(0, Math.round(Number(to.startTick ?? to.start ?? 0)));
  const endMonth = Math.max(startMonth, Math.round(Number(
    to.endTick ?? to.end ?? startMonth + Number(to.duration || 1)
  )));
  const earlyMonth = Math.min(endMonth, startMonth + 12);
  const consolidationMonth = Math.min(endMonth, startMonth + Math.max(18, Math.round((endMonth - startMonth) * 0.72)));
  const earlyCollaboration = periodEvolutionScore(earlyMonth, "collaboration");
  const earlyResource = periodEvolutionScore(earlyMonth, "resource");
  const earlyGap = Math.abs(earlyCollaboration - earlyResource);
  const lateRiskExposure = periodEvolutionScore(consolidationMonth, "risk");
  const lateRegionalBalance = periodEvolutionScore(consolidationMonth, "regional");

  const sourceStart = Math.max(0, Math.round(Number(from.startTick ?? from.start ?? 0)));
  const sourceEnd = Math.max(startMonth, endMonth);
  let actualCount = 0;
  let possibleCount = 0;
  for (let month = sourceStart; month <= sourceEnd; month += 1) {
    for (const metric of periodMetricDefinitions) {
      possibleCount += 1;
      if (Number.isFinite(readPeriodEvolutionActualScore(month, metric.key))) actualCount += 1;
    }
  }
  const actualCoverage = possibleCount ? actualCount / possibleCount : 0;
  const confidence = actualCoverage >= 0.75
    ? "High-confidence result"
    : actualCoverage >= 0.35
      ? "Moderate-confidence result"
      : actualCoverage > 0
        ? "Partial monthly evidence"
        : "Scenario-model estimate";
  const confidenceTone = actualCoverage >= 0.75
    ? "high"
    : actualCoverage >= 0.35
      ? "moderate"
      : "modeled";
  const broadImprovement = positiveRows.length === metricRows.length;
  const headline = broadImprovement
    ? "Broad-based improvement, with an incomplete operational conversion"
    : averageDelta >= 0
      ? "Overall improvement is positive but uneven across dimensions"
      : "The selected transition introduces net performance pressure";
  const summary = broadImprovement
    ? `P${to.index} improves all ${metricRows.length} monitored dimensions. ${leading.label} leads (${formatPeriodDelta(leading.delta)}), while Resource Flow converts ${conversionRate}% of the collaboration gain and ${lagging.label} records the smallest change (${formatPeriodDelta(lagging.delta)}).`
    : `P${to.index} changes the composite score by ${formatPeriodDelta(averageDelta, 1)} points. Gains are concentrated in ${leading.label}, while ${lagging.label} requires corrective attention.`;
  const leadingShare = positiveTotal > 0 ? Math.round((leading.delta / positiveTotal) * 100) : 0;

  return {
    confidence,
    confidenceTone,
    evidenceSource: actualCoverage >= 0.75
      ? "Actual Monthly Data"
      : actualCoverage > 0
        ? "Mixed Monthly Evidence"
        : "Modeled Monthly Trace",
    compositeDelta: formatPeriodDelta(averageDelta, 1),
    improvedCount: `${positiveRows.length}/${metricRows.length}`,
    headline,
    summary,
    breadth: `${positiveRows.length}/${metricRows.length} metrics improved`,
    stats: [
      { label: "Composite average", value: formatPeriodDelta(averageDelta, 1) },
      { label: "Dimensions improved", value: `${positiveRows.length}/${metricRows.length}` },
      { label: "Leading gain", value: formatPeriodDelta(leading.delta) }
    ],
    findings: [
      {
        title: `${leading.label} is the primary transition driver`,
        detail: `${leading.fromScore} -> ${leading.toScore}; contributes ${leadingShare}% of total positive movement across the monitored dimensions.`,
        value: formatPeriodDelta(leading.delta),
        icon: leading.icon,
        tone: leading.tone
      },
      {
        title: "Operational conversion trails collaboration",
        detail: `Resource Flow improves ${formatPeriodDelta(resource.delta)} versus ${formatPeriodDelta(collaboration.delta)} for Collaboration, leaving a ${Math.max(0, conversionGap)}-point conversion gap.`,
        value: `${conversionRate}%`,
        icon: LineChart,
        tone: "green",
        warning: conversionRate < 80
      },
      {
        title: `${lagging.label} is the weakest improvement signal`,
        detail: `${lagging.fromScore} -> ${lagging.toScore}; the endpoint remains ${lagging.toScore}, but marginal improvement is only ${formatPeriodDelta(lagging.delta)}.`,
        value: formatPeriodDelta(lagging.delta),
        icon: lagging.icon,
        tone: lagging.tone,
        warning: lagging.delta <= 2
      }
    ],
    impactPath: [
      { label: "Collaboration", value: formatPeriodDelta(collaboration.delta), tone: "blue" },
      { label: "Resource Flow", value: formatPeriodDelta(resource.delta), tone: "green" },
      { label: "Risk Control", value: formatPeriodDelta(risk.delta), tone: "purple" }
    ],
    conversionRate,
    conversionNote: conversionGap > 0
      ? `${Math.max(0, conversionGap)} points of collaboration improvement have not yet converted into resource-flow performance.`
      : "Resource-flow improvement is keeping pace with collaboration gains.",
    supportSignals: [
      { label: "Regional Balance", value: formatPeriodDelta(regional.delta) },
      { label: "Lifecycle Momentum", value: formatPeriodDelta(lifecycle.delta) }
    ],
    evidenceWindows: [
      {
        month: `M${startMonth}`,
        title: "Transition boundary",
        detail: `P${to.index} begins after ${from.duration} months of ${from.shortTitle.toLowerCase()} conditions.`
      },
      {
        month: `M${earlyMonth}`,
        title: "Early operating response",
        detail: `Collaboration reaches ${earlyCollaboration}, while Resource Flow reaches ${earlyResource}; the operating response remains ${earlyGap} point${earlyGap === 1 ? "" : "s"} apart.`
      },
      {
        month: `M${consolidationMonth}`,
        title: "Consolidation check",
        detail: `Risk Exposure is ${lateRiskExposure} and Regional Balance is ${lateRegionalBalance}, showing whether the gain has become resilient and spatially distributed.`
      }
    ],
    actions: [
      {
        title: "Close the conversion gap",
        detail: `Raise the next-period Resource Flow gain from ${formatPeriodDelta(resource.delta)} toward at least ${formatPeriodDelta(Math.max(resource.delta, collaboration.delta - 1))}.`,
        icon: Target
      },
      {
        title: "Protect the risk-control gain",
        detail: `Track the three-month Risk Exposure average after Month ${consolidationMonth}; investigate any reversal above ${Math.min(100, lateRiskExposure + 3)}.`,
        icon: Shield
      },
      {
        title: "Spread gains beyond core corridors",
        detail: "Direct new partnerships and resource routes toward lower-participation regions before the next period review.",
        icon: Network
      }
    ]
  };
});

const periodRegionalDeltas = computed(() => {
  const rows = (analyticsRegionMap.value.length ? analyticsRegionMap.value : analyticsFallbackRegionRows()).slice(0, 5);
  const positions = [
    ["42%", "28%"],
    ["58%", "38%"],
    ["34%", "56%"],
    ["68%", "62%"],
    ["50%", "72%"]
  ];
  return rows.map((row, index) => ({
    name: row.label || analyticsCityLabel(row.name),
    tone: index < 2 ? "positive" : index === 2 ? "neutral" : "negative",
    x: positions[index]?.[0] || "50%",
    y: positions[index]?.[1] || "50%"
  }));
});

const periodFlowDeltaSources = computed(() => [
  { name: "Guangzhou", color: analyticsCityColors.Guangzhou },
  { name: "Shenzhen", color: analyticsCityColors.Shenzhen },
  { name: "Dongguan", color: analyticsCityColors.Dongguan }
]);

const periodFlowDeltaTargets = computed(() => [
  { name: "Shenzhen", color: analyticsCityColors.Shenzhen },
  { name: "Hong Kong", color: analyticsCityColors["Hong Kong SAR"] },
  { name: "Zhuhai", color: analyticsCityColors.Zhuhai }
]);

const periodFlowDeltaLinks = computed(() => [
  { id: "flow-1", path: "M70,32 C118,30 142,38 190,42", color: "rgba(255,122,34,.64)", width: 7 },
  { id: "flow-2", path: "M70,78 C116,70 142,82 190,84", color: "rgba(47,111,221,.58)", width: 5 },
  { id: "flow-3", path: "M70,122 C112,118 146,126 190,126", color: "rgba(10,157,98,.54)", width: 4 }
]);

const periodCorridorDeltas = computed(() => {
  const rows = analyticsCorridors.value.slice(0, 4);
  const max = Math.max(1, ...rows.map((row) => Number(row.value || 0)));
  return rows.map((row, index) => ({
    rank: index + 1,
    label: row.label,
    value: `+${Math.round(Number(row.value || 0) * 0.18)}`,
    percent: `${Math.round((Number(row.value || 0) / max) * 100)}%`,
    color: index % 2 ? "#2f6fdd" : "#ff7a16"
  }));
});

function syncWorkflowFromAnalyticsDashboard(dashboard = analyticsDashboard.value) {
  const horizon = Number(dashboard?.horizon_months || dashboard?.horizon || dashboard?.ticks || 0);
  if (Number.isFinite(horizon) && horizon > 0) workflowTicks.value = horizon;
  if (workflowPolicyRows.value.length && !workflowPolicyRows.value.some((row) => row.id === selectedExternalPolicyId.value)) {
    selectedExternalPolicyId.value = workflowPolicyRows.value[0].id;
  }
  if (workflowEventRows.value.length && !workflowEventRows.value.some((row) => row.id === selectedExternalEventId.value)) {
    selectedExternalEventId.value = workflowEventRows.value[0].id;
  }
}

function updateTimelineShellHeight() {
  return null;
}

function resizeCharts() {
  chartCache.forEach((chart) => {
    if (chart && !chart.isDisposed?.()) chart.resize();
  });
}

function buildWorkflowConfigurationPayload() {
  const periods = workflowPeriodRows.value.map((row, index) => ({
    ...row,
    phase_id: row.phase_id || row.period_id || row.id || `PH${String(index + 1).padStart(3, "0")}`,
    name: row.title || row.name || `Period ${index + 1}`,
    start_tick: Number(row.startTick ?? row.start_tick ?? 0),
    end_tick: Number(row.endTick ?? row.end_tick ?? 0),
    phase_type: row.phase_type || row.stage || "simulation"
  }));
  const policies = workflowPolicyRows.value.map((row, index) => ({
    ...row,
    intervention_id: row.intervention_id || row.id || `INT${String(index + 1).padStart(3, "0")}`,
    policy_id: row.policy_id || (index === 0 ? activePolicy.value?.id : undefined),
    name: row.title || row.name || `Policy ${index + 1}`,
    apply_tick: Number(row.startTick ?? row.start_tick ?? row.apply_tick ?? 0),
    end_tick: Number(row.endTick ?? row.end_tick ?? workflowTicks.value),
    target_scope: row.target_scope || "all_agents",
    target_roles: Array.isArray(row.target_roles) ? row.target_roles : [],
    target_regions: Array.isArray(row.target_regions) ? row.target_regions : (selectedClusterDetail.value?.coverage || [])
  }));
  const events = workflowEventRows.value.map((row, index) => ({
    ...row,
    event_id: row.event_id || row.id || `WFE${String(index + 1).padStart(3, "0")}`,
    name: row.title || row.name || `External Event ${index + 1}`,
    tick: Number(row.startTick ?? row.start_tick ?? row.tick ?? 0),
    event_type: row.event_type || row.type || "external_event"
  }));
  const agentRegions = selectedClusterDetail.value?.coverage || [];
  return {
    name: workflowData.value?.name || "GBA Policy Simulation Workflow",
    selected_cluster_id: activeCluster.value?.id || workflowData.value?.selected_cluster_id || "",
    horizon_years: Math.max(1, Math.round(Number(workflowTicks.value || 60) / 12)),
    time_step: "monthly",
    phases: periods,
    interventions: policies,
    events,
    execution_logic: {
      ...(workflowData.value?.execution_logic || {}),
      total_ticks: Number(workflowTicks.value || 60),
      timeline_items: workflowTimelineItems.value
    },
    configuration: {
      ...(workflowData.value?.configuration || {}),
      procurement_execution: { ...procurementExecution.value },
      periods,
      policies,
      events,
      agent_source: useDatabaseAgents.value ? "database" : "default",
      agent_count: useDatabaseAgents.value ? Number(simulationAgentCount.value || 6000) : null,
      agent_regions: agentRegions,
      max_tender_invites: Number(maxTenderInvites.value || 40),
      use_prior_network_edges: Boolean(usePriorNetworkEdges.value && useDatabaseAgents.value)
    }
  };
}

function externalChangeTypeKey(change) {
  const raw = String(change?.type || change?.kind || change?.title || "").toLowerCase();
  if (raw.includes("event") || raw.includes("shock") || raw.includes("market")) return "event";
  if (raw.includes("sustain") || raw.includes("carbon") || raw.includes("green")) return "sustainability";
  if (raw.includes("digital") || raw.includes("technology") || raw.includes("bim") || raw.includes("data")) return "technology";
  if (raw.includes("procurement") || raw.includes("tender") || raw.includes("bid")) return "procurement";
  return "regulation";
}

function externalChangeProfileFor(change, index = 0) {
  const key = externalChangeTypeKey(change);
  const profiles = {
    regulation: {
      tone: "blue",
      score: 72,
      riskProbability: 32,
      deltas: { approval: 10, collaboration: 14, resource: 8, cost: -4, risk: -6, innovation: 5 },
      riskText: "Policy effect is positive when qualification recognition and compliance interpretation remain clear.",
      recommendation: "Monitor qualification recognition, tender participation, and compliance burden through the first post-policy period."
    },
    sustainability: {
      tone: "green",
      score: 64,
      riskProbability: 41,
      deltas: { approval: 5, collaboration: 7, resource: 9, cost: 7, risk: -2, innovation: 15 },
      riskText: "Green incentives may create cost and supplier-capacity pressure if subsidy timing is slower than project demand.",
      recommendation: "Pair incentives with supplier capacity monitoring and phased green-material requirements."
    },
    technology: {
      tone: "purple",
      score: 69,
      riskProbability: 36,
      deltas: { approval: 6, collaboration: 11, resource: 7, cost: 4, risk: -3, innovation: 17 },
      riskText: "Digital policy works when owners, designers, QS, and contractors share data standards.",
      recommendation: "Run adoption in pilots before requiring full digital workflows across low-readiness firms."
    },
    procurement: {
      tone: "orange",
      score: 58,
      riskProbability: 44,
      deltas: { approval: 3, collaboration: 6, resource: 4, cost: -2, risk: -8, innovation: 4 },
      riskText: "Procurement reform reduces award risk but can slow projects if criteria become too complex.",
      recommendation: "Track tender response count, bid-evaluation duration, and award-to-contract delay."
    },
    event: {
      tone: "red",
      score: -38,
      riskProbability: 68,
      deltas: { approval: -7, collaboration: -5, resource: -12, cost: 10, risk: 16, innovation: -3 },
      riskText: "Market events become risky when resource occupancy, cost overrun, or supplier scarcity rise together.",
      recommendation: "Use reserve suppliers, staged owner initiation, and short review windows after the event."
    }
  };
  const profile = profiles[key] || profiles.regulation;
  const scoreAdjustment = key === "event" ? -index * 4 : index * 2;
  return {
    ...profile,
    key,
    score: clampNumber(profile.score + scoreAdjustment, -95, 96),
    riskProbability: clampNumber(profile.riskProbability + (key === "event" ? index * 5 : index * 2), 5, 92)
  };
}

const externalFocusModes = [
  { key: "all", label: "All Changes", icon: Activity },
  { key: "policy", label: "Policies", icon: Shield },
  { key: "event", label: "Events", icon: Target },
  { key: "combo", label: "Combined", icon: Network },
  { key: "window", label: "Time Window", icon: Timer }
];

function periodForTick(tick) {
  return periodAnalysisPeriods.value.find((period) => tick >= period.start && tick <= period.end) || periodAnalysisPeriods.value[0];
}

const simulationExternalPolicyRows = computed(() => workflowPolicyRows.value.map((item, index) => {
  const startTick = Math.round(Number(item.startTick || 0));
  const endTick = Math.max(startTick, Math.round(Number(item.endTick ?? item.startTick ?? startTick)));
  const period = periodForTick(startTick);
  const profile = externalChangeProfileFor({ ...item, kind: "policy" }, index);
  return {
    ...profile,
    id: item.id || `policy-${index + 1}`,
    source: "policy",
    title: item.title || `Policy ${index + 1}`,
    shortTitle: formatPeriodShortTitle(item.title || `Policy ${index + 1}`),
    description: item.note || "Policy intervention configured in the current simulation timeline.",
    startTick,
    endTick,
    icon: Shield,
    timeLabel: timelineMonthRangeLabel({ ...item, startTick, endTick, type: "policy" }),
    periodLabel: period ? `P${period.index} ${period.shortTitle}` : "No period",
    modeLabel: "Policy change"
  };
}));

const simulationExternalEventRows = computed(() => workflowEventRows.value.map((item, index) => {
  const startTick = Math.round(Number(item.startTick || 0));
  const period = periodForTick(startTick);
  const profile = externalChangeProfileFor({ ...item, kind: "event" }, index);
  return {
    ...profile,
    id: item.id || `event-${index + 1}`,
    source: "event",
    title: item.title || `Event ${index + 1}`,
    shortTitle: formatPeriodShortTitle(item.title || `Event ${index + 1}`),
    description: item.note || "External event configured in the current simulation timeline.",
    startTick,
    endTick: startTick,
    icon: Target,
    timeLabel: timelineMonthLabel(startTick),
    periodLabel: period ? `P${period.index} ${period.shortTitle}` : "No period",
    modeLabel: "Event focus"
  };
}));

const selectedExternalPolicy = computed(() =>
  simulationExternalPolicyRows.value.find((row) => row.id === selectedExternalPolicyId.value) ||
  simulationExternalPolicyRows.value[0] ||
  null
);

const selectedExternalEvent = computed(() =>
  simulationExternalEventRows.value.find((row) => row.id === selectedExternalEventId.value) ||
  simulationExternalEventRows.value[0] ||
  null
);

const externalTimeWindowRows = computed(() => {
  const anchor = selectedExternalPolicy.value || selectedExternalEvent.value;
  const total = Math.max(1, Number(workflowTicks.value || 60));
  const anchorStart = Number(anchor?.startTick ?? Math.round(total * 0.4));
  const anchorEnd = Number(anchor?.endTick ?? anchorStart);
  const rows = [
    {
      id: "before",
      title: "Before External Change",
      startTick: Math.max(0, anchorStart - 12),
      endTick: Math.max(0, anchorStart),
      basis: "pre-change baseline"
    },
    {
      id: "during",
      title: "Direct Exposure Window",
      startTick: anchorStart,
      endTick: Math.min(total, Math.max(anchorEnd, anchorStart + 12)),
      basis: "policy/event exposure"
    },
    {
      id: "after",
      title: "Post-change Response",
      startTick: Math.min(total, Math.max(anchorEnd, anchorStart + 12)),
      endTick: Math.min(total, Math.max(anchorEnd, anchorStart + 24)),
      basis: "lagged response"
    }
  ];
  return rows.map((row) => ({
    ...row,
    range: `${timelineMonthLabel(row.startTick)} - ${timelineMonthLabel(row.endTick)}`
  }));
});

const selectedExternalWindow = computed(() =>
  externalTimeWindowRows.value.find((row) => row.id === selectedExternalWindowId.value) ||
  externalTimeWindowRows.value[1] ||
  externalTimeWindowRows.value[0]
);

function combineExternalDeltas(primary = {}, secondary = {}, secondaryWeight = 0.55) {
  const keys = ["approval", "collaboration", "resource", "cost", "risk", "innovation"];
  return Object.fromEntries(keys.map((key) => [
    key,
    Number((Number(primary[key] || 0) + Number(secondary[key] || 0) * secondaryWeight).toFixed(1))
  ]));
}

const externalPortfolioFocus = computed(() => {
  const items = [...simulationExternalPolicyRows.value, ...simulationExternalEventRows.value];
  const fallback = selectedExternalPolicy.value || selectedExternalEvent.value || externalChangeProfileFor({ kind: "policy" });
  const sourceItems = items.length ? items : [fallback];
  const keys = ["approval", "collaboration", "resource", "cost", "risk", "innovation"];
  const deltas = Object.fromEntries(keys.map((key) => {
    const total = sourceItems.reduce((sum, item) => sum + Number(item?.deltas?.[key] || 0), 0);
    const average = total / Math.max(1, sourceItems.length);
    return [key, Number(average.toFixed(1))];
  }));
  const startTick = Math.min(...sourceItems.map((item) => Number(item?.startTick || 0)));
  const endTick = Math.max(...sourceItems.map((item) => Number(item?.endTick ?? item?.startTick ?? 0)));
  const score = sourceItems.reduce((sum, item) => sum + Number(item?.score || 0), 0) / Math.max(1, sourceItems.length);
  const riskProbability = sourceItems.reduce((sum, item) => sum + Number(item?.riskProbability || 0), 0) / Math.max(1, sourceItems.length);
  const policyCount = simulationExternalPolicyRows.value.length;
  const eventCount = simulationExternalEventRows.value.length;
  const scopeLabel = [
    `${policyCount} polic${policyCount === 1 ? "y" : "ies"}`,
    `${eventCount} event${eventCount === 1 ? "" : "s"}`
  ].join(" · ");
  return {
    id: "external-portfolio",
    title: "External Change Portfolio",
    description: "Integrated analysis across all external policies, events, combinations, and timing windows in the current simulation.",
    source: "portfolio",
    tone: riskProbability >= 55 ? "orange" : "green",
    icon: Activity,
    startTick,
    endTick,
    timeLabel: `${timelineMonthLabel(startTick)} - ${timelineMonthLabel(endTick)}`,
    periodLabel: scopeLabel,
    modeLabel: "All external changes",
    score: clampNumber(score, -95, 96),
    riskProbability: clampNumber(riskProbability + (eventCount && policyCount ? 6 : 0), 0, 95),
    deltas,
    riskText: "Portfolio risk is read from repeated-run probability, lifecycle exposure, and trigger thresholds across all configured external changes.",
    recommendation: "Read the portfolio first, then inspect policies, events, combinations, or time windows only when a signal needs explanation."
  };
});

const externalPortfolioScopeRows = computed(() => {
  const policyCount = simulationExternalPolicyRows.value.length;
  const eventCount = simulationExternalEventRows.value.length;
  const periodCount = externalFocusPeriodRows.value.filter((period) => period.exposure > 0).length;
  return [
    { label: "External Items", value: `${policyCount + eventCount}`, note: `${policyCount} policies · ${eventCount} events`, icon: Activity, tone: "blue" },
    { label: "Analysis Window", value: externalPortfolioFocus.value.timeLabel, note: "Current workflow timeline", icon: Timer, tone: "orange" },
    { label: "Affected Periods", value: `${periodCount}`, note: "Periods with direct or lagged exposure", icon: LineChart, tone: "green" },
    { label: "Run Basis", value: "Paired runs", note: "Repeated comparison, not one path", icon: Copy, tone: "purple" }
  ];
});

const selectedExternalFocus = computed(() => {
  const policy = selectedExternalPolicy.value;
  const event = selectedExternalEvent.value;
  const window = selectedExternalWindow.value;
  if (externalFocusMode.value === "all") {
    return externalPortfolioFocus.value;
  }
  if (externalFocusMode.value === "event") {
    return event || {
      id: "no-event",
      title: "No Event Configured",
      description: "This simulation timeline does not contain an external event yet.",
      source: "event",
      tone: "red",
      icon: Target,
      startTick: 0,
      endTick: 0,
      timeLabel: "N/A",
      periodLabel: "N/A",
      modeLabel: "Event focus",
      score: 0,
      riskProbability: 0,
      deltas: {},
      riskText: "No event risk can be measured until an event is configured.",
      recommendation: "Add an external event in Workflow to enable event analysis."
    };
  }
  if (externalFocusMode.value === "combo") {
    const basePolicy = policy || simulationExternalPolicyRows.value[0];
    const baseEvent = event || simulationExternalEventRows.value[0];
    if (!basePolicy || !baseEvent) {
      return {
        id: "combo-unavailable",
        title: "Policy + Event Combination",
        description: "Combination analysis needs both a policy intervention and an external event in the current workflow.",
        source: "combo",
        tone: "orange",
        icon: Network,
        startTick: Number(basePolicy?.startTick || baseEvent?.startTick || 0),
        endTick: Number(basePolicy?.endTick || baseEvent?.endTick || 0),
        timeLabel: "Missing policy or event",
        periodLabel: "N/A",
        modeLabel: "Combination focus",
        score: Number(basePolicy?.score || 0),
        riskProbability: clampNumber(Number(basePolicy?.riskProbability || 0) + 12, 0, 92),
        deltas: basePolicy?.deltas || {},
        riskText: "Combination risk cannot be tested until both external inputs are configured.",
        recommendation: "Add at least one policy and one event to the workflow timeline."
      };
    }
    const deltas = combineExternalDeltas(basePolicy.deltas, baseEvent.deltas, 0.65);
    return {
      id: `${basePolicy.id}+${baseEvent.id}`,
      title: `${basePolicy.shortTitle} + ${baseEvent.shortTitle}`,
      description: "Combined analysis estimates whether a policy remains robust when an external event occurs in the same simulation horizon.",
      source: "combo",
      tone: "orange",
      icon: Network,
      startTick: Math.min(basePolicy.startTick, baseEvent.startTick),
      endTick: Math.max(basePolicy.endTick, baseEvent.endTick),
      timeLabel: `${basePolicy.timeLabel} / ${baseEvent.timeLabel}`,
      periodLabel: `${basePolicy.periodLabel}; ${baseEvent.periodLabel}`,
      modeLabel: "Combination focus",
      score: clampNumber(basePolicy.score + baseEvent.score * 0.36, -95, 96),
      riskProbability: clampNumber((basePolicy.riskProbability + baseEvent.riskProbability) / 2 + 12, 0, 95),
      deltas,
      riskText: "Combination risk appears when policy-driven demand meets event-driven resource or cost pressure.",
      recommendation: "Compare paired seeds across Baseline, Policy Only, Event Only, and Policy + Event before judging robustness."
    };
  }
  if (externalFocusMode.value === "window") {
    const anchor = policy || event;
    const exposureFactor = window?.id === "before" ? 0.35 : window?.id === "after" ? 0.7 : 1;
    const base = anchor || externalChangeProfileFor({ kind: "policy" });
    const deltas = Object.fromEntries(Object.entries(base.deltas || {}).map(([key, value]) => [key, Number((Number(value) * exposureFactor).toFixed(1))]));
    return {
      ...(anchor || {}),
      id: `window-${window?.id || "during"}`,
      source: "window",
      title: window?.title || "Selected Time Window",
      description: `Time-window analysis compares ${window?.range || "the selected range"} against the selected external change context.`,
      tone: window?.id === "before" ? "blue" : window?.id === "after" ? "green" : "orange",
      icon: Timer,
      startTick: window?.startTick || 0,
      endTick: window?.endTick || 0,
      timeLabel: window?.range || "N/A",
      periodLabel: window?.basis || "time window",
      modeLabel: "Time-window focus",
      score: clampNumber(Number(base.score || 0) * exposureFactor, -95, 96),
      riskProbability: clampNumber(Number(base.riskProbability || 0) * (window?.id === "before" ? 0.45 : window?.id === "after" ? 0.82 : 1), 0, 95),
      deltas,
      riskText: "Window risk depends on whether early signals persist after the external change exposure.",
      recommendation: "Use before/during/after windows to separate immediate impact from lagged lifecycle response."
    };
  }
  return policy || {
    id: "no-policy",
    title: "No Policy Configured",
    description: "This simulation timeline does not contain a policy intervention yet.",
    source: "policy",
    tone: "blue",
    icon: Shield,
    startTick: 0,
    endTick: 0,
    timeLabel: "N/A",
    periodLabel: "N/A",
    modeLabel: "Policy change",
    score: 0,
    riskProbability: 0,
    deltas: {},
    riskText: "No policy risk can be measured until a policy is configured.",
    recommendation: "Add a policy intervention in Workflow to enable policy risk analysis."
  };
});

const externalMetricDefinitions = [
  { key: "approval", label: "Approval Efficiency", icon: Shield, color: "#2f6fdd" },
  { key: "collaboration", label: "Collaboration", icon: Network, color: "#2563eb" },
  { key: "resource", label: "Resource Flow", icon: LineChart, color: "#0a9d62" },
  { key: "cost", label: "Cost Burden", icon: BarChart3, color: "#f59e0b", lowerIsBetter: true },
  { key: "risk", label: "Risk Exposure", icon: AlertTriangle, color: "#ef4444", lowerIsBetter: true },
  { key: "innovation", label: "Innovation Capacity", icon: Sparkles, color: "#8b5cf6" }
];

const externalFocusMetricRows = computed(() => externalMetricDefinitions.map((definition) => {
  const focus = selectedExternalFocus.value;
  const delta = Number(focus.deltas?.[definition.key] ?? 0);
  const negative = definition.lowerIsBetter ? delta > 0 : delta < 0;
  const direction = definition.lowerIsBetter
    ? delta <= 0 ? "improves" : "worsens"
    : delta >= 0 ? "improves" : "declines";
  const scopePhrase = focus.source === "portfolio"
    ? "across the external-change portfolio"
    : `under the active ${focus.modeLabel.toLowerCase()}`;
  return {
    ...definition,
    delta,
    negative,
    width: `${clampNumber(38 + Math.abs(delta) * 3.4, 10, 100)}%`,
    deltaLabel: `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pts`,
    detail: `${definition.label} ${direction} ${scopePhrase}.`
  };
}));

const externalFocusProfileStats = computed(() => {
  const focus = selectedExternalFocus.value;
  const affectedPeriods = externalFocusPeriodRows.value.filter((period) => period.exposure > 0).length;
  return [
    { label: "Analysis Scope", value: focus.modeLabel },
    { label: "Timing", value: focus.timeLabel },
    { label: focus.source === "portfolio" ? "External Items" : "Linked Period", value: focus.periodLabel },
    { label: "Affected Periods", value: affectedPeriods || "0" }
  ];
});

const externalFocusPeriodRows = computed(() => {
  const focus = selectedExternalFocus.value;
  const strongestDelta = externalFocusMetricRows.value.reduce((max, metric) =>
    Math.abs(metric.delta) > Math.abs(max) ? metric.delta : max,
  0);
  return periodAnalysisPeriods.value.map((period) => {
    const start = Number(focus.startTick || 0);
    const end = Number(focus.endTick ?? start);
    const isPoint = focus.source === "event" || end <= start;
    const directExposure = isPoint
      ? start >= period.start && start <= period.end
      : Math.max(0, Math.min(period.end, end) - Math.max(period.start, start)) / Math.max(1, period.duration);
    const followOn = !directExposure && period.start > start;
    const exposure = directExposure || (followOn ? 0.28 : 0);
    const delta = strongestDelta * exposure;
    return {
      id: period.id,
      label: `P${period.index}`,
      title: period.shortTitle,
      range: period.range,
      exposure,
      width: `${clampNumber(12 + exposure * 88, 10, 100)}%`,
      delta: `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`,
      negative: delta < 0
    };
  });
});

const externalRiskSummary = computed(() => {
  const probability = Math.round(Number(selectedExternalFocus.value.riskProbability || 0));
  return {
    probability: `${probability}%`,
    label: probability >= 65 ? "High risk probability" : probability >= 40 ? "Moderate risk probability" : "Controlled risk probability",
    tone: probability >= 65 ? "red" : probability >= 40 ? "orange" : "green"
  };
});

const externalRiskMatrixRows = computed(() => {
  const focus = selectedExternalFocus.value;
  const cost = Number(focus.deltas?.cost || 0);
  const risk = Number(focus.deltas?.risk || 0);
  const resource = Number(focus.deltas?.resource || 0);
  const collaboration = Number(focus.deltas?.collaboration || 0);
  return [
    {
      title: "Compliance / Cost Burden",
      evidence: cost > 0 ? "Cost pressure rises after external-change exposure." : "Cost burden is not the dominant risk in this scope.",
      probability: `${Math.round(clampNumber(28 + Math.max(0, cost) * 4, 8, 88))}%`,
      level: cost > 6 ? "H" : cost > 0 ? "M" : "L",
      tone: cost > 6 ? "red" : cost > 0 ? "orange" : "green"
    },
    {
      title: "Tender Competition Weakening",
      evidence: collaboration < 4 ? "Low collaboration gain may reduce bidder depth." : "Collaboration signal supports bidder depth.",
      probability: `${Math.round(clampNumber(36 - collaboration * 1.2 + Math.max(0, risk) * 2, 10, 82))}%`,
      level: collaboration < 4 || risk > 8 ? "M" : "L",
      tone: collaboration < 4 || risk > 8 ? "orange" : "green"
    },
    {
      title: "Resource Congestion",
      evidence: resource < 0 ? "Resource flow declines under the active external-change scope." : "Resource flow remains supportive.",
      probability: `${Math.round(clampNumber(30 + Math.max(0, -resource) * 3 + Math.max(0, risk) * 2.2, 12, 90))}%`,
      level: resource < -6 || risk > 10 ? "H" : resource < 0 ? "M" : "L",
      tone: resource < -6 || risk > 10 ? "red" : resource < 0 ? "orange" : "green"
    }
  ];
});

const externalRiskTriggerRows = computed(() => [
  {
    label: "Compliance burden threshold",
    condition: "Risk appears when compliance cost rises faster than adaptation capacity.",
    threshold: "cost +8 pts",
    icon: FileCog,
    tone: "orange"
  },
  {
    label: "Tender depth threshold",
    condition: "Competition risk appears when qualified bidders fall below a healthy tender pool.",
    threshold: "< 3 bidders",
    icon: HardHat,
    tone: "red"
  },
  {
    label: "Resource occupancy threshold",
    condition: "Delay risk appears when contractor/supplier capacity stays occupied across periods.",
    threshold: "> 78%",
    icon: Package,
    tone: "orange"
  },
  {
    label: "Regional concentration threshold",
    condition: "Uneven benefits appear when cross-region links concentrate in one corridor.",
    threshold: "HHI > .32",
    icon: MapPin,
    tone: "blue"
  }
]);

const externalOverallAssessment = computed(() => {
  const focus = selectedExternalFocus.value;
  const score = Math.round(Number(focus.score || 0));
  const strongest = [...externalFocusMetricRows.value].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];
  const tone = score < 0 ? "red" : externalRiskSummary.value.tone === "red" ? "orange" : "green";
  return {
    badge: score < 0 ? "Pressure case" : externalRiskSummary.value.label,
    icon: score < 0 ? AlertTriangle : TrendingUp,
    title: score < 0 ? "External change creates net pressure" : "External change is net supportive",
    text: `${focus.title} is evaluated as a repeated-run comparison. The main signal is ${strongest?.label || "N/A"} (${strongest?.deltaLabel || "+0.0 pts"}), while the risk reading should be judged by probability and trigger conditions instead of one single trajectory.`,
    tone
  };
});

const externalOverallFormRows = computed(() => {
  const focus = selectedExternalFocus.value;
  const affectedPeriods = externalFocusPeriodRows.value.filter((period) => period.exposure > 0).length;
  const strongest = [...externalFocusMetricRows.value].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];
  const topRisk = externalRiskMatrixRows.value[0];
  const primaryTrigger = externalRiskTriggerRows.value[0];
  const score = Math.round(Number(focus.score || 0));
  return [
    {
      label: "Analysis Scope",
      value: focus.title,
      note: `${focus.modeLabel} · ${focus.timeLabel} · ${focus.periodLabel}`
    },
    {
      label: "Experiment Basis",
      value: "Repeated runs",
      note: "Compare baseline and selected-change cases with paired seeds."
    },
    {
      label: "Overall Impact",
      value: `${score >= 0 ? "+" : ""}${score}`,
      note: `${affectedPeriods || 0} affected period${affectedPeriods === 1 ? "" : "s"} in the current simulation timeline.`,
      negative: score < 0
    },
    {
      label: "Primary Signal",
      value: strongest ? `${strongest.label} ${strongest.deltaLabel}` : "N/A",
      note: strongest?.detail || "No metric signal is available for the active external-change scope.",
      negative: strongest?.negative
    },
    {
      label: "Risk Reading",
      value: externalRiskSummary.value.probability,
      note: externalRiskSummary.value.label,
      negative: externalRiskSummary.value.tone === "red" || externalRiskSummary.value.tone === "orange"
    },
    {
      label: "Top Risk",
      value: topRisk?.title || "N/A",
      note: topRisk?.evidence || "No risk evidence is available yet.",
      negative: topRisk?.tone === "red" || topRisk?.tone === "orange"
    },
    {
      label: "Trigger Condition",
      value: primaryTrigger?.threshold || "N/A",
      note: primaryTrigger?.label || "No trigger condition is configured.",
      negative: true
    },
    {
      label: "Recommended Read",
      value: focus.recommendation ? "Review" : "Compare",
      note: "Use paired-run evidence before drawing a policy conclusion."
    }
  ];
});

const externalRunDistributionRows = computed(() => {
  const focus = selectedExternalFocus.value;
  const rows = [
    ["Net external effect", Number(focus.score || 0), false],
    ["Risk probability", Number(focus.riskProbability || 0), true],
    ["Collaboration lift", Number(focus.deltas?.collaboration || 0), false],
    ["Cost burden", Number(focus.deltas?.cost || 0), true],
    ["Lifecycle delay risk", Number(focus.deltas?.risk || 0), true]
  ];
  return rows.map(([label, value, lowerIsBetter], index) => {
    const normalized = clampNumber(50 + Number(value) * (lowerIsBetter ? 0.35 : 0.45), 6, 94);
    const spread = clampNumber(18 + index * 3 + Math.abs(Number(value)) * 0.32, 14, 44);
    return {
      label,
      value: `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(index === 1 ? 0 : 1)}`,
      negative: lowerIsBetter ? Number(value) > 0 : Number(value) < 0,
      rangeStart: `${clampNumber(normalized - spread / 2, 0, 96)}%`,
      rangeWidth: `${spread}%`,
      meanPosition: `${normalized}%`
    };
  });
});

const externalLifecycleRows = computed(() => {
  const focus = selectedExternalFocus.value;
  const approval = Number(focus.deltas?.approval || 0);
  const collaboration = Number(focus.deltas?.collaboration || 0);
  const cost = Number(focus.deltas?.cost || 0);
  const risk = Number(focus.deltas?.risk || 0);
  return [
    { label: "Owner Initiation", evidence: "Owner project release may respond to policy confidence or event pressure.", delta: `${approval >= 0 ? "+" : ""}${(approval * 0.6).toFixed(1)}`, icon: Building2, tone: approval >= 0 ? "green" : "red", negative: approval < 0 },
    { label: "Approval", evidence: "Approval confidence is directly affected by policy certainty and external shock timing.", delta: `${approval >= 0 ? "+" : ""}${approval.toFixed(1)}`, icon: Shield, tone: approval >= 0 ? "blue" : "red", negative: approval < 0 },
    { label: "Tendering", evidence: "Bidder depth and qualification fit change when compliance and competition conditions shift.", delta: `${collaboration >= 0 ? "+" : ""}${collaboration.toFixed(1)}`, icon: HardHat, tone: collaboration >= 0 ? "green" : "orange", negative: collaboration < 0 },
    { label: "Contract Award", evidence: "Award risk depends on tender response quality and contractor capacity.", delta: `${risk <= 0 ? "+" : "-"}${Math.abs(risk * 0.55).toFixed(1)}`, icon: FileText, tone: risk <= 0 ? "green" : "red", negative: risk > 0 },
    { label: "Construction Progress", evidence: "Progress risk appears when cost burden and resource congestion persist after award.", delta: `${cost <= 0 && risk <= 0 ? "+" : "-"}${Math.abs(cost + risk * 0.4).toFixed(1)}`, icon: LineChart, tone: cost <= 0 && risk <= 0 ? "green" : "orange", negative: cost > 0 || risk > 0 }
  ];
});

const externalRegionRoleRows = computed(() => {
  const regionRows = (analyticsRegionMap.value.length ? analyticsRegionMap.value : analyticsFallbackRegionRows())
    .slice()
    .sort((a, b) => Number(b.value || 0) - Number(a.value || 0))
    .slice(0, 3);
  const max = Math.max(1, ...regionRows.map((row) => Number(row.value || 0)));
  const regions = regionRows.map((row, index) => ({
    rank: index + 1,
    label: row.label || analyticsCityLabel(row.name),
    reason: "Regional sensitivity from project activity, firm density, and cross-region links.",
    value: `${Math.round(Number(row.value || 0))}`,
    width: `${Math.round((Number(row.value || 0) / max) * 100)}%`,
    color: analyticsCityColors[normalizeCityName(row.name || row.label)] || analyticsCityColors.Others
  }));
  const roles = [
    { label: "Owner", value: "High", width: "84%", color: "#ff7a16", reason: "Project initiation and timing decisions respond first." },
    { label: "Contractor", value: "Med", width: "68%", color: "#2f6fdd", reason: "Tendering and capacity risk concentrate here." },
    { label: "Supplier", value: "Med", width: "58%", color: "#0a9d62", reason: "Resource scarcity appears through supply reliability." }
  ].map((row, index) => ({ ...row, rank: regions.length + index + 1 }));
  return [...regions, ...roles].slice(0, 6);
});

const externalAnalysisSummary = computed(() => {
  const focus = selectedExternalFocus.value;
  const strongest = [...externalFocusMetricRows.value].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];
  return {
    notes: [
      {
        title: "Effect Interpretation",
        text: `${focus.title} should be read as a repeated-run experiment. The strongest simulated signal is ${strongest?.label || "N/A"} (${strongest?.deltaLabel || "+0.0 pts"}), not a one-off deterministic result.`,
        icon: LineChart,
        tone: strongest?.negative ? "red" : "green"
      },
      {
        title: "Risk Interpretation",
        text: focus.riskText || "Risk should be evaluated by trigger conditions and repeated-run probability, not by a single visible trajectory.",
        icon: AlertTriangle,
        tone: externalRiskSummary.value.tone
      },
      {
        title: "Recommended Experiment",
        text: focus.recommendation || "Compare Baseline, Policy Only, Event Only, and Policy + Event with paired random seeds before drawing policy conclusions.",
        icon: Target,
        tone: "orange"
      }
    ]
  };
});

function selectExternalPolicy(policyId) {
  selectedExternalPolicyId.value = policyId;
}

function selectExternalEvent(eventId) {
  selectedExternalEventId.value = eventId;
}
const simulationMonth = computed(() => runtimeState.value?.current_date || `Tick ${performanceHistory.value.length || 0}`);
const playbackMaxTick = computed(() => {
  const timelineMax = playbackTimeline.value.reduce((max, row) => Math.max(max, Number(row.tick || 0)), 0);
  return Math.max(timelineMax, runtimeState.value?.current_tick || 0, performanceHistory.value.length || 0, 1);
});
const currentTimelinePoint = computed(() => {
  if (!playbackTimeline.value.length) return null;
  return playbackTimeline.value.find((row) => Number(row.tick) === Number(currentPlaybackTick.value)) ||
    [...playbackTimeline.value].reverse().find((row) => Number(row.tick) <= Number(currentPlaybackTick.value)) ||
    playbackTimeline.value[0];
});
const currentStageLabel = computed(() => eventTypeLabel(currentTimelinePoint.value?.stage || "runtime"));
const playbackPercent = computed(() => Math.round((Number(currentPlaybackTick.value || 1) / playbackMaxTick.value) * 100));
const playbackIntervalMs = computed(() => Math.max(160, Math.round(850 / Number(playbackSpeed.value || 1))));
const timelineMilestones = computed(() => {
  const maxTick = playbackMaxTick.value;
  const rows = playbackTimeline.value.filter((row, index) =>
    index === 0 ||
    index === playbackTimeline.value.length - 1 ||
    row.completed_projects ||
    row.important_events?.length
  );
  const sparseRows = rows.filter((row, index) => index === 0 || index === rows.length - 1 || row.completed_projects || row.important_events?.length);
  return sparseRows.slice(0, 12).map((row) => ({
    ...row,
    left: `${Math.max(2, Math.min(98, (Number(row.tick) / maxTick) * 100))}%`
  }));
});
const currentTimelineEvents = computed(() => {
  const events = currentTimelinePoint.value?.important_events || [];
  if (events.length) return events.slice(0, 5);
  if (!currentTimelinePoint.value) return [];
  return [{
    event_id: `tick-${currentTimelinePoint.value.tick}`,
    tick: currentTimelinePoint.value.tick,
    event_type: "state_snapshot",
    description: `${currentTimelinePoint.value.active_projects} active projects, ${currentTimelinePoint.value.engaged_agents} engaged firms, ${currentTimelinePoint.value.collaboration_edges} collaboration links.`
  }];
});
const enterpriseImportantEventTypes = new Set([
  "project_opportunity_initiated",
  "consultant_team_appointed",
  "tender_documents_prepared",
  "tender_opened",
  "bid_submitted",
  "bid_evaluation_completed",
  "contract_awarded",
  "supplier_selected",
  "construction_progress_updated",
  "project_completed",
  "agent_engaged",
  "agent_standby",
  "agent_recalled",
  "agent_released"
]);
const selectedEnterpriseName = computed(() => {
  const agent = selectedEnterpriseHistory.value?.agent || {};
  return formatEnterpriseDisplayName(agent.name || selectedRuntimeEnterprise.value?.name, "Enterprise");
});
const selectedEnterpriseDisplayName = computed(() => {
  const name = selectedEnterpriseName.value || "Enterprise";
  const compact = formatEnterpriseDisplayName(name, "Enterprise");
  return compact.length > 30 ? `${compact.slice(0, 27)}...` : compact;
});
const selectedProjectDisplayName = computed(() => {
  const name = selectedRuntimeProject.value?.name || "Project";
  const compact = String(name).replace(/\s+/g, " ").trim();
  return compact.length > 30 ? `${compact.slice(0, 27)}...` : compact;
});
const selectedEnterpriseSummary = computed(() => selectedEnterpriseHistory.value?.summary || {
  joined_projects: 0,
  event_count: 0,
  active_ticks: 0,
  release_events: 0,
  joined_project_ids: []
});
const selectedEnterpriseAgentProfile = computed(() => selectedEnterpriseHistory.value?.agent || {});
const selectedEnterpriseHistoryTick = computed(() => {
  const candidates = [
    currentPlaybackTick.value,
    runtimeState.value?.current_tick,
    selectedEnterpriseHistory.value?.current_tick
  ]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);
  return Math.max(1, Math.min(...(candidates.length ? candidates : [1])));
});
const selectedEnterpriseEvents = computed(() =>
  (selectedEnterpriseHistory.value?.events || [])
    .filter((event) => eventAtOrBeforePlayback(event))
    .slice(-40)
    .reverse()
);
const selectedEnterpriseActivityTimeline = computed(() =>
  (selectedEnterpriseHistory.value?.activity_timeline || [])
    .filter((event) => eventAtOrBeforePlayback(event))
);
const selectedEnterpriseStatusRows = computed(() =>
  (selectedEnterpriseHistory.value?.status_timeline || [])
    .filter((row) => eventAtOrBeforePlayback(row))
    .filter((row) => row.status && row.status !== "free")
    .slice(-24)
    .reverse()
);
const selectedEnterpriseImportantInfo = computed(() => {
  const agent = selectedEnterpriseAgentProfile.value;
  const enterprise = selectedRuntimeEnterprise.value || {};
  const resourceCapacity = Number(agent.total_resource_capacity ?? 1);
  const occupied = Number(agent.occupied_resource ?? 0);
  const freeResource = Math.max(0, resourceCapacity - occupied);
  const source = agent.source_category || agent.data_source || agent.sourceCategory || (agent.ai_generated ? "synthetic" : "");
  const sourceLabel = source ? String(source).replace("real_user", "User data").replace("real_public", "Public registry").replace("synthetic", "Synthetic") : "Simulation pool";
  const qualification = Number(agent.qualification_level ?? agent.qualification ?? 0.5);
  const crossRegion = Number(agent.cross_region_experience ?? 0.5);
  return [
    { label: "Role", value: roleDisplayName(enterprise.role || agent.role) },
    { label: "Region", value: normalizeCityName(enterprise.city || agent.region || "GBA") },
    { label: "Data source", value: sourceLabel },
    { label: "Resource free", value: `${Math.round(freeResource * 100)}%` },
    { label: "Qualification", value: `${Math.round(Math.max(0, Math.min(1, qualification)) * 100)}%` },
    { label: "Cross-region", value: `${Math.round(Math.max(0, Math.min(1, crossRegion)) * 100)}%` }
  ];
});
const selectedEnterpriseCapabilities = computed(() => {
  const agent = selectedEnterpriseAgentProfile.value;
  const role = String(selectedRuntimeEnterprise.value?.role || agent.role || "").toLowerCase();
  const rows = [
    ["Financial strength", agent.financial_capacity ?? agent.financial_strength],
    ["Technical capability", agent.technical_capability],
    ["Management", agent.management_capability],
    ["Policy adaptability", agent.policy_adaptability]
  ];
  if (role.includes("contractor")) {
    rows.splice(2, 0, ["Construction", agent.construction_capability], ["Safety", agent.safety_management_capability], ["Quality", agent.quality_management_capability]);
  } else if (role.includes("supplier")) {
    rows.splice(2, 0, ["Supply reliability", agent.supply_reliability], ["Material quality", agent.material_quality]);
  } else if (role.includes("architect") || role.includes("design")) {
    rows.splice(2, 0, ["Design", agent.design_capability]);
  } else if (role.includes("qs")) {
    rows.splice(2, 0, ["Cost estimation", agent.cost_estimation_capability]);
  } else if (role.includes("owner") || role.includes("developer")) {
    rows.splice(2, 0, ["Payment reliability", agent.payment_reliability], ["Decision speed", agent.decision_speed]);
  }
  return rows
    .filter(([, value]) => Number.isFinite(Number(value)))
    .slice(0, 4)
    .map(([label, value]) => ({
      label,
      score: Math.round(Math.max(0, Math.min(1, Number(value))) * 100),
      value: `${Math.round(Math.max(0, Math.min(1, Number(value))) * 100)}%`
    }));
});
const selectedEnterpriseImportantEvents = computed(() => {
  const seen = new Set();
  const important = [];
  selectedEnterpriseEvents.value.forEach((event) => {
    const type = String(event.event_type || "").toLowerCase();
    const projectId = event.project_id || event.data?.project_id || event.data?.projectId || "";
    const key = `${type}-${projectId}-${event.tick}`;
    if (!enterpriseImportantEventTypes.has(type) || seen.has(key)) return;
    seen.add(key);
    important.push(event);
  });
  if (important.length) return important.slice(0, 5);
  const operationSeen = new Set();
  return [...selectedEnterpriseActivityTimeline.value]
    .sort((a, b) => Number(b.tick || 0) - Number(a.tick || 0))
    .filter((event) => {
      const key = event.data?.operation || event.event_type || event.tick;
      if (operationSeen.has(key)) return false;
      operationSeen.add(key);
      return true;
    })
    .slice(0, 5);
});
const selectedEnterpriseDetailedActivity = computed(() => {
  const backendRows = selectedEnterpriseActivityTimeline.value.map((event) => ({ ...event, source: event.data?.activity_source || "activity" }));
  const fallbackRows = selectedEnterpriseEvents.value.map((event) => ({ ...event, source: "event" }));
  return (backendRows.length ? backendRows : fallbackRows)
    .sort((a, b) => Number(b.tick || 0) - Number(a.tick || 0))
    .slice(0, 72);
});
const displayedEnterpriseActivity = computed(() =>
  enterpriseActivityExpanded.value ? selectedEnterpriseDetailedActivity.value : selectedEnterpriseImportantEvents.value
);
const selectedEnterpriseLatestActivity = computed(() => {
  const activity = selectedEnterpriseDetailedActivity.value[0];
  if (activity) return activity;
  return selectedEnterpriseEvents.value.find((event) => String(event.event_type || "").toLowerCase() !== "agent_operation")
    || selectedEnterpriseEvents.value[0];
});
const selectedEnterpriseCurrentStatus = computed(() => {
  const row = selectedEnterpriseStatusRows.value[0];
  return statusLabel(row?.status || selectedRuntimeEnterprise.value?.status || "active");
});
const selectedEnterpriseCurrentDescription = computed(() => {
  const event = selectedEnterpriseLatestActivity.value;
  if (event?.description) return friendlyEventDescription(event);
  const role = selectedRuntimeEnterprise.value?.role || "Enterprise";
  const city = selectedRuntimeEnterprise.value?.city || "GBA";
  return `${role} operating in ${city} with current simulation resource status.`;
});
const selectedProjectParticipants = computed(() => {
  const project = selectedRuntimeProject.value;
  if (!project?.projectId) return [];
  const participants = new Map();

  const addParticipant = (entry, fallbackRole = "Participant", fallbackStatus = "selected") => {
    const id = String(entry?.agent_id || entry?.agentId || entry?.id || entry || "").trim();
    if (!id || participants.has(id)) return;
    const enterprise = runtimeMapEnterprises.value.find((item) => item.nodeId === id || item.node?.id === id);
    const role = entry?.role || enterprise?.role || enterprise?.node?.role || fallbackRole || "Participant";
    const city = normalizeCityName(entry?.city || enterprise?.city || enterprise?.node?.city || project.city || "");
    participants.set(id, {
      id,
      name: formatEnterpriseDisplayName(entry?.name || enterprise?.node?.name || enterprise?.name || id, roleDisplayName(role)),
      role,
      city,
      status: entry?.status || enterprise?.status || fallbackStatus
    });
  };

  (project.participants || []).forEach((participant) => addParticipant(participant, participant?.role));
  [
    [project.ownerId, "Owner"],
    [project.selectedArchitectId, "Architect"],
    [project.selectedEngineerId, "Engineer"],
    [project.selectedQsId, "QS"],
    [project.selectedContractorId, "Contractor"],
    ...(project.selectedSupplierIds || []).map((id) => [id, "Supplier"])
  ].forEach(([id, role]) => addParticipant(id, role));

  if (participants.size < 3) {
    runtimeLinks.value.forEach((link) => {
      if (link.source_id === project.projectId && link.target_id) addParticipant(link.target_id, "Participant", "linked");
      if (link.target_id === project.projectId && link.source_id) addParticipant(link.source_id, "Participant", "linked");
    });
  }

  return Array.from(participants.values())
    .sort((a, b) => participantRoleOrder(a.role) - participantRoleOrder(b.role) || a.name.localeCompare(b.name))
    .slice(0, 8);
});
const selectedProjectEvents = computed(() => {
  const project = selectedRuntimeProject.value;
  if (!project) return [];
  const projectId = String(project.projectId || "").toLowerCase();
  const projectName = String(project.name || "").toLowerCase();
  const timelineEvents = playbackTimeline.value
    .flatMap((row) =>
      (row.important_events || []).map((event) => ({
        ...event,
        tick: event.tick || row.tick
      }))
    )
    .filter((event) => isEventForProject(event, projectId, projectName))
    .filter(isProjectLifecycleEvent);
  const mergedEvents = dedupeProjectEvents([
    ...timelineEvents,
    ...projectLifecycleMilestones(project)
  ]).sort((a, b) => Number(a.tick || 0) - Number(b.tick || 0));
  const currentTick = projectLifecycleDisplayTick(project);
  const createdTick = normalizeProjectCreatedTick(project);
  return mergedEvents
    .filter((event) => Number(event.tick || createdTick) <= currentTick + 1)
    .slice(-8);
});
const evaluationBars = computed(() => [
  { label: "Economic Growth", value: analyticsDashboard.value?.policy_evaluation_summary?.score_breakdown?.economic_growth || 85 },
  { label: "Environmental Impact", value: analyticsDashboard.value?.policy_evaluation_summary?.score_breakdown?.environmental_impact || 84 },
  { label: "Social Well-being", value: analyticsDashboard.value?.policy_evaluation_summary?.score_breakdown?.social_wellbeing || 79 },
  { label: "Innovation Capacity", value: analyticsDashboard.value?.policy_evaluation_summary?.score_breakdown?.innovation_capacity || policyImpactScore.value },
  { label: "Reg. & Gov. Effectiveness", value: analyticsDashboard.value?.policy_evaluation_summary?.score_breakdown?.regulatory_governance_effectiveness || 72 }
]);
const fallbackProjectCatalog = [
  { project_id: "demo-shenzhen", city: "Shenzhen", name: "Metro Line Extension", project_type: "infrastructure", status: "ongoing", progress: 74 },
  { project_id: "demo-guangzhou", city: "Guangzhou", name: "AI Innovation Park", project_type: "digital", status: "building", progress: 67 },
  { project_id: "demo-foshan", city: "Foshan", name: "Green Manufacturing Hub", project_type: "industrial", status: "ongoing", progress: 82 },
  { project_id: "demo-hong-kong", city: "Hong Kong SAR", name: "Port Expansion", project_type: "infrastructure", status: "ongoing", progress: 53 },
  { project_id: "demo-macao", city: "Macao SAR", name: "GBA Data Center", project_type: "digital", status: "completed", progress: 88 },
  { project_id: "demo-huizhou", city: "Huizhou", name: "Energy Storage Factory", project_type: "industrial", status: "building", progress: 35 }
];
const fallbackEnterpriseSource = computed(() => {
  const sourceAgents = agentRows.value.length ? agentRows.value : staticAgents;
  return sourceAgents.slice(0, 120).map((agent, index) => {
    const city = normalizeCityName(agent.region || agent.city || gbaCityMeta[index % gbaCityMeta.length].name);
    const { longitude, latitude } = lngLatObject(city);
    return {
      agent_id: agent.agent_id || `fallback-agent-${index}`,
      name: agent.name || `GBA Enterprise ${index + 1}`,
      role: agent.role || "Contractor",
      city,
      longitude,
      latitude,
      status: index % 4 === 0 ? "standby" : "active",
      engaged_project_ids: []
    };
  });
});
const runtimeMapProjects = computed(() => {
  const sourceProjects = runtimeState.value?.map?.projects?.length
    ? runtimeState.value.map.projects
    : fallbackProjectCatalog.map((project) => ({
        ...project,
        ...lngLatObject(project.city)
      }));
  const cityCounts = new Map();
  return sourceProjects.map((project) => {
    const city = normalizeCityName(project.city);
    const count = cityCounts.get(city) || 0;
    cityCounts.set(city, count + 1);
    const [longitude, latitude] = realisticProjectLngLat(project, city, count);
    return {
      name: project.name,
      value: [longitude, latitude, Math.round(project.progress || 0)],
      city,
      projectId: project.project_id,
      status: project.status,
      stage: project.stage,
      projectType: project.project_type,
      quality: Number(project.quality_score || 0),
      delayDays: Number(project.delay_days || 0),
      costOverrun: Number(project.cost_overrun_ratio || 0),
      progress: Math.round(project.progress || 0),
      ownerId: project.owner_id,
      selectedArchitectId: project.selected_architect_id,
      selectedEngineerId: project.selected_engineer_id,
      selectedQsId: project.selected_qs_id,
      selectedContractorId: project.selected_contractor_id,
      selectedSupplierIds: project.selected_supplier_ids || [],
      participants: project.participants || [],
      initialBudget: Number(project.initial_budget || 0),
      estimatedCost: Number(project.estimated_cost || 0),
      contractSum: Number(project.contract_sum || 0),
      plannedDuration: Number(project.planned_duration || 0),
      bids: project.bids || [],
      contracts: project.contracts || [],
      createdTick: normalizeProjectCreatedTick(project)
    };
  });
});
const runtimeLinks = computed(() => {
  const map = runtimeState.value?.map;
  if (!map) return fallbackRuntimeLinks.value;
  return [...(map.resource_flows || []), ...(map.collaboration_links || [])];
});
const runtimeMapEnterprises = computed(() => {
  const links = runtimeLinks.value;
  const linkedIds = new Set(links.flatMap((link) => [link.source_id, link.target_id]));
  runtimeMapProjects.value.forEach((project) => {
    projectParticipantIds(project).forEach((id) => linkedIds.add(id));
  });
  const sourceEnterprises = runtimeState.value?.map?.enterprises?.length ? runtimeState.value.map.enterprises : fallbackEnterpriseSource.value;
  const enterprises = selectVisibleEnterprises(sourceEnterprises, linkedIds, 550);
  const cityCounts = new Map();
  return enterprises.map((enterprise) => {
    const city = normalizeCityName(enterprise.city);
    const count = cityCounts.get(city) || 0;
    cityCounts.set(city, count + 1);
    const [longitude, latitude] = realisticEnterpriseLngLat(enterprise, city, count);
    const node = {
      id: enterprise.agent_id,
      name: enterprise.name,
      city,
      role: enterprise.role,
      status: linkedIds.has(enterprise.agent_id) ? "linked" : enterprise.status,
      shortName: String(enterprise.name || "").replace(/SyntheticConstructionAgent|模拟/g, "").slice(0, 16),
      className: roleClass(enterprise.role)
    };
    return {
      name: node.shortName || node.id,
      value: [longitude, latitude, enterpriseStatusWeight(node.status)],
      nodeId: enterprise.agent_id,
      node,
      role: enterprise.role,
      city,
      status: node.status
    };
  });
});
const runtimeMapPointLookup = computed(() => {
  const lookup = new Map();
  runtimeMapProjects.value.forEach((point) => lookup.set(point.projectId, [point.value[0], point.value[1]]));
  runtimeMapEnterprises.value.forEach((point) => lookup.set(point.nodeId, [point.value[0], point.value[1]]));
  return lookup;
});
const runtimeMapResourceLines = computed(() => buildRuntimeMapLines("resource_flow"));
const runtimeMapCollaborationLines = computed(() => buildRuntimeMapLines("collaboration_link"));
const runtimeMapLinkCount = computed(() => runtimeMapResourceLines.value.length + runtimeMapCollaborationLines.value.length);
const mapZoomLabel = computed(() => `${Math.round(runtimeMapZoom.value * 100)}%`);
const runtimeMapIsSparse = computed(() => runtimeMapEnterprises.value.length <= 12 && runtimeMapProjects.value.length <= 3);
const selectedRuntimeEnterpriseId = computed(() => selectedRuntimeEnterprise.value?.id || "");
const selectedRuntimeProjectId = computed(() => selectedRuntimeProject.value?.projectId || "");
const runtimeSvgMapTransform = computed(() => {
  const scale = Number(runtimeMapZoom.value || 1);
  const centerX = 500;
  const centerY = 315;
  const pan = runtimeMapPan.value || { x: 0, y: 0 };
  return `translate(${Number(pan.x.toFixed(1))} ${Number(pan.y.toFixed(1))}) translate(${centerX} ${centerY}) scale(${scale}) translate(${-centerX} ${-centerY})`;
});
const selectedRuntimeRegionMarker = computed(() => {
  if (!selectedRuntimeRegion.value) return null;
  const city = cityMetaFor(selectedRuntimeRegion.value);
  const [x, y] = projectSvgPoint(city.center[0], city.center[1]);
  return { x, y, name: city.name };
});
const runtimeSvgEnterprises = computed(() =>
  runtimeMapEnterprises.value.map((point) => {
    const [x, y] = projectSvgPoint(point.value[0], point.value[1]);
    const linked = point.node?.status === "linked";
    const selected = selectedRuntimeEnterpriseId.value === point.nodeId;
    return {
      id: point.nodeId,
      x,
      y,
      radius: selected ? (linked ? 7.6 : 6.6) : (linked ? 4.6 : 2.7),
      selectionRadius: linked ? 11.5 : 10,
      color: mapRoleColor(point.role),
      className: roleClass(point.role),
      linked,
      selected,
      node: point.node
    };
  })
);
const runtimeSvgProjects = computed(() =>
  runtimeMapProjects.value.map((project) => {
    const [x, y] = projectSvgPoint(project.value[0], project.value[1]);
    const stageLabel = statusLabel(project.stage || project.status || project.projectType || "project");
    const projectName = shortProjectName(project.name || project.city || project.projectId);
    const progress = Math.round(project.progress || 0);
    const circumference = 2 * Math.PI * 15.5;
    const progressLength = Math.max(2.5, (Math.max(0, Math.min(100, progress)) / 100) * circumference);
    return {
      id: project.projectId,
      x,
      y,
      city: project.city?.replace(" SAR", "") || project.name,
      progress,
      progressDash: `${progressLength.toFixed(1)} ${circumference.toFixed(1)}`,
      name: projectName,
      stageLabel,
      color: projectColor(project.stage, project.status),
      selected: selectedRuntimeProjectId.value === project.projectId,
      node: {
        ...project,
        name: projectName,
        stageLabel
      }
    };
  })
);
const runtimeSvgLinks = computed(() =>
  runtimeLinks.value.slice(0, 180).map((link, index) => {
    const source = runtimeMapPointLookup.value.get(link.source_id) || linkCoordinate(link, "source");
    const target = runtimeMapPointLookup.value.get(link.target_id) || linkCoordinate(link, "target");
    const [x1, y1] = projectSvgPoint(source[0], source[1]);
    const [x2, y2] = projectSvgPoint(target[0], target[1]);
    const curve = link.cross_city ? 34 + (index % 4) * 8 : 18;
    const midX = (x1 + x2) / 2;
    const midY = (y1 + y2) / 2 - curve;
    return {
      id: link.link_id || `${link.source_id}-${link.target_id}-${index}`,
      type: link.link_type,
      path: `M${x1} ${y1} Q${Number(midX.toFixed(1))} ${Number(midY.toFixed(1))} ${x2} ${y2}`,
      width: Math.max(1.2, Math.min(3.2, Number(link.strength || 0.5) * 2.4))
    };
  })
);
const fallbackRuntimeLinks = computed(() => {
  const enterprises = fallbackEnterpriseSource.value.slice(0, 36);
  return enterprises.map((enterprise, index) => {
    const project = fallbackProjectCatalog[index % fallbackProjectCatalog.length];
    const source = lngLatObject(enterprise.city);
    const target = lngLatObject(project.city);
    return {
      link_id: `fallback-link-${index}`,
      source_id: enterprise.agent_id,
      target_id: project.project_id,
      source_latitude: source.latitude,
      source_longitude: source.longitude,
      target_latitude: target.latitude,
      target_longitude: target.longitude,
      link_type: index % 3 === 0 ? "resource_flow" : "collaboration_link",
      strength: 0.42 + (index % 7) * 0.07,
      cross_city: normalizeCityName(enterprise.city) !== normalizeCityName(project.city),
      status: "active"
    };
  });
});
const mapBubbles = computed(() => Array.from({ length: 95 }, (_, index) => ({
  id: index,
  x: `${6 + ((index * 37) % 88)}%`,
  y: `${8 + ((index * 53) % 80)}%`,
  size: `${5 + (index % 5) * 2}px`,
  type: ["orange", "blue", "purple", "green"][index % 4]
})));

function capability(agent, field, fallback) {
  return Number(agent[field] ?? fallback);
}

function defaultAgentForm() {
  return {
    name: "",
    role: "Contractor",
    region: "Shenzhen",
    sourceCategory: "real_user",
    enterpriseType: "Main Contractor",
    scale: "Medium Scale",
    ownership: "Private",
    serviceScope: "GBA",
    employees: 120,
    annualRevenue: 0.6,
    description: "",
    activeRegions: "Shenzhen, Guangzhou",
    preferredPartners: "Local contractor, green supplier",
    qualificationLevel: 0.62,
    financialCapacity: 0.58,
    technicalCapability: 0.62,
    managementCapability: 0.60,
    totalResourceCapacity: 0.75,
    riskPreference: 0.50,
    collaborationPreference: 0.66,
    crossRegionExperience: 0.52,
    policyAdaptability: 0.56,
    designCapability: 0.50,
    costEstimationCapability: 0.52,
    constructionCapability: 0.68,
    qualityManagementCapability: 0.64,
    safetyManagementCapability: 0.62,
    supervisionCapability: 0.50,
    supplyReliability: 0.50,
    materialQuality: 0.50,
    paymentReliability: 0.58,
    decisionSpeed: 0.60
  };
}

function defaultAiAgentForm() {
  return {
    prompt: "",
    role: "Contractor",
    region: "Shenzhen",
    projectFocus: "Infrastructure",
    collaborationProfile: "Cross-region coordinator"
  };
}

function roleIcon(role) {
  const normalizedRole = roleDisplayName(role);
  return {
    Owner: Building2,
    Architect: DraftingCompass,
    QS: UserRound,
    Consultant: UserRound,
    Contractor: HardHat,
    Supplier: Package,
    Government: Shield
  }[normalizedRole] || Building2;
}

function roleColor(role) {
  const normalizedRole = roleDisplayName(role);
  return {
    Owner: "blue",
    Architect: "teal",
    QS: "brown",
    Consultant: "brown",
    Contractor: "orange",
    Supplier: "purple",
    Government: "green"
  }[normalizedRole] || "orange";
}

function roleClass(role) {
  const normalized = String(role || "").toLowerCase();
  if (normalized.includes("owner") || normalized.includes("developer")) return "developer";
  if (normalized.includes("contractor")) return "contractor";
  if (normalized.includes("supplier")) return "supplier";
  if (normalized.includes("government")) return "government";
  return "consultant";
}

function mapRoleColor(role) {
  const roleType = roleClass(role);
  return {
    developer: "#2563eb",
    contractor: "#0891b2",
    supplier: "#7c3aed",
    government: "#475569",
    consultant: "#db2777"
  }[roleType];
}

function projectColor(stage, status) {
  const normalizedStatus = String(status || "").toLowerCase();
  const normalizedStage = String(stage || "").toLowerCase();
  if (normalizedStatus.includes("completed") || normalizedStage.includes("closed") || normalizedStage.includes("completion")) return "#2f9e57";
  if (normalizedStatus.includes("failed") || normalizedStatus.includes("suspended")) return "#be3a34";
  if (normalizedStage.includes("construction")) return "#f08a24";
  if (normalizedStage.includes("tender") || normalizedStage.includes("contract")) return "#7c3aed";
  if (normalizedStage.includes("approval")) return "#2563eb";
  return "#f08a24";
}

function normalizeCityName(value) {
  const raw = String(value || "").trim();
  if (!raw) return "Shenzhen";
  if (gbaCityNameByRegion.has(raw)) return gbaCityNameByRegion.get(raw);
  const lower = raw.toLowerCase();
  if (lower.includes("hong kong") || raw.includes("香港")) return "Hong Kong SAR";
  if (lower.includes("macau") || lower.includes("macao") || raw.includes("澳门") || raw.includes("澳門")) return "Macao SAR";
  const withoutSuffix = raw.replace(/市$/, "");
  return gbaCityNameByRegion.get(withoutSuffix) || raw;
}

function cityMetaFor(value) {
  const name = normalizeCityName(value);
  return gbaCityMeta.find((city) => city.name === name || city.nameZh === name) || gbaCityMeta.find((city) => city.name === "Shenzhen");
}

function lngLatObject(cityName) {
  const [longitude, latitude] = cityMetaFor(cityName).center;
  return { longitude, latitude };
}

function resolveLngLat(node, fallbackCity) {
  const longitude = Number(node?.longitude ?? node?.lng);
  const latitude = Number(node?.latitude ?? node?.lat);
  if (Number.isFinite(longitude) && Number.isFinite(latitude) && longitude >= 112 && longitude <= 116 && latitude >= 21 && latitude <= 25) {
    return [longitude, latitude];
  }
  return cityMetaFor(fallbackCity || node?.city).center;
}

function realisticEnterpriseLngLat(enterprise, city, index) {
  const normalizedCity = normalizeCityName(city || enterprise?.city);
  const [longitude, latitude] = resolveLngLat(enterprise, normalizedCity);
  if (hasSpecificLngLat(enterprise, normalizedCity, longitude, latitude)) return [longitude, latitude];
  return sampleLngLatInsideCity(
    normalizedCity,
    enterprise?.agent_id || enterprise?.name || `enterprise-${index}`,
    enterprise?.role || "enterprise",
    "enterprise"
  );
}

function realisticProjectLngLat(project, city, index) {
  const normalizedCity = normalizeCityName(city || project?.city);
  const [longitude, latitude] = resolveLngLat(project, normalizedCity);
  if (hasSpecificLngLat(project, normalizedCity, longitude, latitude)) return [longitude, latitude];
  return sampleLngLatInsideCity(
    normalizedCity,
    project?.project_id || project?.name || `project-${index}`,
    project?.project_type || "project",
    "project"
  );
}

function hasSpecificLngLat(node, city, longitude, latitude) {
  const rawLongitude = Number(node?.longitude ?? node?.lng);
  const rawLatitude = Number(node?.latitude ?? node?.lat);
  if (!Number.isFinite(rawLongitude) || !Number.isFinite(rawLatitude)) return false;
  const center = cityMetaFor(city).center;
  const closeToCityCenter = Math.abs(longitude - center[0]) < 0.03 && Math.abs(latitude - center[1]) < 0.03;
  const feature = gbaFeatureIndex.byName.get(normalizeCityName(city));
  return !closeToCityCenter && (!feature || featureContainsLngLat(feature, longitude, latitude));
}

function sampleLngLatInsideCity(city, id, roleOrType, mode) {
  const normalizedCity = normalizeCityName(city);
  const cacheKey = `${mode}:${normalizedCity}:${id}:${roleOrType}`;
  if (spatialPointCache.has(cacheKey)) return spatialPointCache.get(cacheKey);
  const feature = gbaFeatureIndex.byName.get(normalizedCity);
  const bounds = gbaFeatureIndex.bounds.get(normalizedCity);
  const center = cityMetaFor(normalizedCity).center;
  if (!feature || !bounds) {
    const fallback = mode === "project"
      ? spreadProjectLngLat(center[0], center[1], normalizedCity, deterministicUnit(cacheKey) * 100, cacheKey)
      : spreadLngLat(center[0], center[1], normalizedCity, deterministicUnit(cacheKey) * 100, cacheKey);
    spatialPointCache.set(cacheKey, fallback);
    return fallback;
  }

  const shrink = normalizedCity === "Macao SAR" ? 0.02 : normalizedCity === "Hong Kong SAR" ? 0.04 : 0.055;
  const minLng = bounds.minLng + (bounds.maxLng - bounds.minLng) * shrink;
  const maxLng = bounds.maxLng - (bounds.maxLng - bounds.minLng) * shrink;
  const minLat = bounds.minLat + (bounds.maxLat - bounds.minLat) * shrink;
  const maxLat = bounds.maxLat - (bounds.maxLat - bounds.minLat) * shrink;
  const attempts = mode === "project" ? 120 : 72;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const u = deterministicUnit(`${cacheKey}:lng:${attempt}`);
    const v = deterministicUnit(`${cacheKey}:lat:${attempt}`);
    const longitude = minLng + u * (maxLng - minLng);
    const latitude = minLat + v * (maxLat - minLat);
    if (featureContainsLngLat(feature, longitude, latitude)) {
      const point = [
        Number(longitude.toFixed(6)),
        Number(latitude.toFixed(6))
      ];
      spatialPointCache.set(cacheKey, point);
      return point;
    }
  }

  const fallback = [
    Number((center[0] + deterministicOffset(`${cacheKey}:fallbackLng`, normalizedCity === "Macao SAR" ? 0.016 : 0.04)).toFixed(6)),
    Number((center[1] + deterministicOffset(`${cacheKey}:fallbackLat`, normalizedCity === "Macao SAR" ? 0.012 : 0.03)).toFixed(6))
  ];
  spatialPointCache.set(cacheKey, fallback);
  return fallback;
}

function selectVisibleEnterprises(sourceEnterprises, linkedIds, limit) {
  const sorted = [...sourceEnterprises].sort(
    (a, b) =>
      enterprisePriority(a, linkedIds) - enterprisePriority(b, linkedIds) ||
      gbaCitySortIndex(a.city) - gbaCitySortIndex(b.city) ||
      String(a.role || "").localeCompare(String(b.role || "")) ||
      String(a.agent_id || "").localeCompare(String(b.agent_id || ""))
  );
  const linked = sorted.filter((enterprise) => linkedIds.has(enterprise.agent_id)).slice(0, Math.min(64, limit));
  const remaining = sorted.filter((enterprise) => !linkedIds.has(enterprise.agent_id));
  const selectedIds = new Set(linked.map((enterprise) => enterprise.agent_id));
  const buckets = new Map(gbaCityMeta.map((city) => [city.name, []]));
  remaining.forEach((enterprise) => {
    const city = normalizeCityName(enterprise.city);
    if (!buckets.has(city)) buckets.set(city, []);
    buckets.get(city).push(enterprise);
  });

  const selected = [...linked];
  while (selected.length < limit && Array.from(buckets.values()).some((bucket) => bucket.length)) {
    for (const city of gbaCityMeta.map((item) => item.name)) {
      if (selected.length >= limit) break;
      const bucket = buckets.get(city) || [];
      const candidate = bucket.shift();
      if (candidate && !selectedIds.has(candidate.agent_id)) {
        selected.push(candidate);
        selectedIds.add(candidate.agent_id);
      }
    }
  }
  return selected;
}

function projectParticipantIds(project) {
  if (!project) return [];
  return Array.from(new Set([
    project.ownerId,
    project.selectedArchitectId,
    project.selectedEngineerId,
    project.selectedQsId,
    project.selectedContractorId,
    ...(project.selectedSupplierIds || []),
    ...(project.participants || []).map((participant) => participant?.agent_id || participant?.agentId || participant?.id)
  ].filter(Boolean).map((id) => String(id))));
}

function participantRoleOrder(role) {
  const normalized = String(role || "").toLowerCase();
  if (normalized.includes("owner") || normalized.includes("developer")) return 0;
  if (normalized.includes("architect") || normalized.includes("design")) return 1;
  if (normalized.includes("engineer")) return 2;
  if (normalized === "qs" || normalized.includes("quantity")) return 3;
  if (normalized.includes("consult")) return 4;
  if (normalized.includes("contractor")) return 5;
  if (normalized.includes("supplier")) return 6;
  if (normalized.includes("government")) return 7;
  return 99;
}

function gbaCitySortIndex(city) {
  const normalized = normalizeCityName(city);
  const index = gbaCityMeta.findIndex((item) => item.name === normalized);
  return index === -1 ? 999 : index;
}

function spreadLngLat(longitude, latitude, city, index, id = "") {
  if (!index) return [
    Number((longitude + deterministicOffset(`${id}:lng0`, 0.006)).toFixed(6)),
    Number((latitude + deterministicOffset(`${id}:lat0`, 0.004)).toFixed(6))
  ];
  const normalizedCity = normalizeCityName(city);
  const scale = normalizedCity === "Macao SAR" ? 0.018 : normalizedCity === "Hong Kong SAR" ? 0.028 : 0.04;
  const angleNoise = deterministicUnit(`${id}:${index}:angle`);
  const distanceNoise = deterministicUnit(`${id}:${index}:distance`);
  const angle = (angleNoise * Math.PI * 2) + index * 0.73;
  const radius = scale * (0.22 + Math.sqrt(distanceNoise) * 0.92);
  return [
    Number((longitude + Math.cos(angle) * radius).toFixed(6)),
    Number((latitude + Math.sin(angle) * radius * 0.58).toFixed(6))
  ];
}

function spreadProjectLngLat(longitude, latitude, city, index, id = "") {
  if (!index) return [
    Number((longitude + deterministicOffset(`${id}:project:lng0`, 0.018)).toFixed(6)),
    Number((latitude + deterministicOffset(`${id}:project:lat0`, 0.012)).toFixed(6))
  ];
  const normalizedCity = normalizeCityName(city);
  const scale = normalizedCity === "Macao SAR" ? 0.035 : normalizedCity === "Hong Kong SAR" ? 0.045 : 0.07;
  const angle = deterministicUnit(`${id}:${index}:project:angle`) * Math.PI * 2;
  const radius = scale * (0.45 + deterministicUnit(`${id}:${index}:project:radius`) * 0.75);
  return [
    Number((longitude + Math.cos(angle) * radius).toFixed(6)),
    Number((latitude + Math.sin(angle) * radius * 0.55).toFixed(6))
  ];
}

function deterministicUnit(value) {
  const text = String(value || "");
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 10000) / 10000;
}

function deterministicOffset(value, amplitude) {
  return (deterministicUnit(value) - 0.5) * amplitude;
}

function shortProjectName(name) {
  const cleaned = String(name || "Project")
    .replace(/\s+PGEN\d+$/i, "")
    .replace(/^GBA baseline\s+/i, "")
    .trim();
  if (!cleaned || cleaned.toLowerCase() === "building project") return "Baseline Building";
  return cleaned.slice(0, 24);
}

function enterprisePriority(enterprise, linkedIds) {
  if (linkedIds.has(enterprise.agent_id)) return 0;
  if (enterprise.status === "active") return 1;
  if (enterprise.status === "standby") return 2;
  return 3;
}

function enterpriseStatusWeight(status) {
  if (status === "linked") return 3;
  if (status === "active") return 2;
  if (status === "standby") return 1;
  return 0.6;
}

function policyIcon(type) {
  const normalized = String(type || "").toLowerCase();
  if (normalized.includes("sustain")) return Shield;
  if (normalized.includes("technology")) return Package;
  if (normalized.includes("procurement") || normalized.includes("governance")) return Building2;
  if (normalized.includes("qualification")) return Network;
  return Handshake;
}

function policyStatusClass(status) {
  return String(status || "draft").toLowerCase().replace(/\s+/g, "-");
}

async function checkBackend() {
  try {
    await api.health();
    backendOnline.value = true;
  } catch {
    backendOnline.value = false;
  }
}

async function loadCatalogData() {
  try {
    const [clustersPage, policiesPage, workflows, dashboard] = await Promise.all([
      clusterApi.list({ page_size: 18 }),
      policyApi.list({ page_size: 32 }),
      workflowApi.list(),
      analyticsApi.dashboard()
    ]);
    backendClusters.value = clustersPage.items || [];
    backendPolicies.value = policiesPage.items || [];
    workflowData.value = workflows?.[0] || null;
    analyticsDashboard.value = dashboard;
    syncWorkflowFromAnalyticsDashboard(dashboard);
    workflowTicks.value = workflowData.value?.horizon_years ? workflowData.value.horizon_years * 12 : workflowTicks.value;
    if (backendClusters.value.length && !backendClusters.value.some((cluster) => cluster.name === selectedCluster.value)) {
      selectedCluster.value = backendClusters.value[0].name;
    }
    if (backendPolicies.value.length && !backendPolicies.value.some((policy) => policy.name === selectedPolicy.value)) {
      selectedPolicy.value = backendPolicies.value[0].name;
    }
    performanceHistory.value = analyticsTrendToHistory(dashboard);
    networkData.value = analyticsNetworkToGraph(dashboard);
    await loadAgentPage();
    await Promise.all([loadSelectedAgentProfile(), loadSelectedClusterDetail(), loadSelectedPolicyDetail()]);
  } catch (error) {
    console.warn("API catalog loading failed; using local fallback data.", error);
  }
}

async function loadAgentPage() {
  if (!backendOnline.value) return;
  agentLoading.value = true;
  try {
    const pageData = await agentApi.list({
      page: agentPage.value,
      page_size: agentPageSize.value,
      keyword: agentKeyword.value.trim() || undefined,
      type: enterpriseTypeFilter.value === "All" ? undefined : enterpriseTypeFilter.value,
      region: enterpriseRegionFilter.value === "All Regions" ? undefined : enterpriseRegionFilter.value
    });
    backendAgents.value = pageData.items || [];
    agentTotal.value = pageData.total || backendAgents.value.length;
    if (backendAgents.value.length && !backendAgents.value.some((agent) => agent.agent_id === selectedAgentId.value)) {
      selectedAgentId.value = backendAgents.value[0].agent_id;
    }
  } catch (error) {
    console.warn("Agent database page loading failed; using local fallback data.", error);
  } finally {
    agentLoading.value = false;
  }
}

async function refreshAgentData() {
  await loadAgentPage();
  nextTick(renderCharts);
}

async function refreshPolicyData() {
  if (!backendOnline.value) {
    nextTick(renderCharts);
    return;
  }
  policyLoading.value = true;
  try {
    const policiesPage = await policyApi.list({ page_size: 32 });
    backendPolicies.value = policiesPage.items || [];
    if (backendPolicies.value.length && !backendPolicies.value.some((policy) => policy.name === selectedPolicy.value)) {
      selectedPolicy.value = backendPolicies.value[0].name;
    }
    await loadSelectedPolicyDetail();
  } catch (error) {
    console.warn("Policy catalog loading failed; using local fallback data.", error);
  } finally {
    policyLoading.value = false;
    nextTick(renderCharts);
  }
}

function selectMappingPolicy(policyId) {
  selectedMappingPolicyId.value = policyId;
  policySummaryPanelOpen.value = true;
  const policy = policyMappingCatalog.find((item) => item.id === policyId);
  if (policy?.scenarios?.length && !policy.scenarios.some((scenario) => scenario.id === selectedMappingScenarioId.value)) {
    selectedMappingScenarioId.value = policy.scenarios[0].id;
  }
  resetMechanismDraftForPolicy(policy);
}

function getPolicyMechanismPackages(policy = activeMappingPolicy.value) {
  const packageIds = policyImplementationPackageMap[policy?.id] || defaultImplementationPackages.map((item) => item.id);
  return packageIds
    .map((packageId) => defaultImplementationPackages.find((item) => item.id === packageId))
    .filter(Boolean);
}

function getPolicyExperimentQuestion(policy = activeMappingPolicy.value) {
  const policyQuestions = {
    "policy-hk-macao-coop": "Which implementation pathway creates the strongest durable increase in Hong Kong and Macao enterprise participation: coordinated rollout, digital-first access, major-project mobilization, or a phased pilot?",
    "policy-approval-fast-track": "Should approval facilitation be launched comprehensively, delivered through a digital-first channel, or piloted for selected projects?",
    "policy-project-supply": "Should the cross-border project pipeline be released broadly, through a digital platform, or in targeted project batches?",
    "policy-qualification-recognition": "Should qualification recognition be implemented GBA-wide, through an online-first route, or as a phased professional-services pilot?"
  };
  if (policyQuestions[policy?.id]) return policyQuestions[policy.id];
  const packageNames = getPolicyMechanismPackages(policy)
    .filter((item) => item.defaultSelected)
    .map((item) => policyUi(item.shortName))
    .slice(0, 4);
  return `Which implementation pathway for ${packageNames.join(", ") || "the mapped policy measures"} produces the strongest robust outcome, and how does delivery scope or enterprise response change the result?`;
}

function getPolicyExperimentQuestionExamples(policy = activeMappingPolicy.value) {
  const examplesByPolicy = {
    "policy-hk-macao-coop": [
      {
        key: "implementation-choice",
        label: "Compare implementation pathways",
        question: "Which implementation pathway creates the strongest durable increase in Hong Kong and Macao enterprise participation: coordinated rollout, digital-first access, major-project mobilization, or a phased pilot?"
      },
      {
        key: "adoption-risk",
        label: "Test weak enterprise response",
        question: "How much of the policy benefit remains if eligible firms respond slowly, platform uptake stays low, or successful firms do not participate again?"
      },
      {
        key: "binding-constraint",
        label: "Identify the binding constraint",
        question: "Which constraint most limits cross-border enterprise participation: qualification recognition, approval speed, project supply, or partner matching?"
      }
    ],
    "policy-approval-fast-track": [
      {
        key: "delivery-choice",
        label: "Compare approval delivery models",
        question: "Should approval facilitation be launched comprehensively, delivered through a digital-first channel, or piloted for selected projects?"
      },
      {
        key: "capacity-stress",
        label: "Stress-test review capacity",
        question: "When application volume rises, which approval model reduces realized processing time without creating a new review backlog?"
      },
      {
        key: "applicant-uptake",
        label: "Test applicant uptake",
        question: "How much benefit survives if eligible applicants continue using existing channels or adopt the fast-track slowly?"
      }
    ],
    "policy-project-supply": [
      {
        key: "release-strategy",
        label: "Compare project release strategies",
        question: "Should the cross-border project pipeline be released broadly, through a digital platform, or in targeted project batches?"
      },
      {
        key: "conversion",
        label: "Test opportunity conversion",
        question: "Which combination of project supply and partner matching converts the largest share of visible opportunities into qualified bids and project starts?"
      },
      {
        key: "firm-response",
        label: "Test uneven firm response",
        question: "Do targeted project releases still improve participation when smaller firms respond less strongly than established enterprises?"
      }
    ],
    "policy-qualification-recognition": [
      {
        key: "recognition-scope",
        label: "Compare recognition scope",
        question: "Should qualification recognition be implemented GBA-wide, through an online-first route, or as a phased professional-services pilot?"
      },
      {
        key: "employer-acceptance",
        label: "Test employer acceptance",
        question: "How much professional entry improves when formal recognition expands but employers adopt recognized qualifications slowly?"
      },
      {
        key: "processing-bottleneck",
        label: "Identify recognition bottlenecks",
        question: "Is professional participation constrained more by recognition coverage, processing time, employer acceptance, or access to suitable projects?"
      }
    ]
  };
  if (examplesByPolicy[policy?.id]) return examplesByPolicy[policy.id];
  const defaultQuestion = getPolicyExperimentQuestion(policy);
  return [
    { key: "implementation-choice", label: "Compare implementation pathways", question: defaultQuestion },
    {
      key: "response-risk",
      label: "Test weak stakeholder response",
      question: `How robust are the expected outcomes of ${policyUi(policy?.name || "this policy")} when stakeholder uptake is slower than expected?`
    },
    {
      key: "binding-constraint",
      label: "Identify the binding constraint",
      question: `Which intervention module is the binding constraint on the main outcome of ${policyUi(policy?.name || "this policy")}?`
    }
  ];
}

function applyPolicyExperimentQuestionExample(question) {
  policyExperimentQuestionDraft.value = question;
  policyExperimentPresetOpen.value = false;
}

function resetMechanismDraftForPolicy(policy = activeMappingPolicy.value) {
  const packages = getPolicyMechanismPackages(policy);
  customAtomicRuleDraft.value = {};
  mechanismStrengthDraft.value = packages.reduce(
    (draft, item) => ({ ...draft, [item.id]: mechanismStrengthDraft.value[item.id] || item.defaultStrength || "medium" }),
    { ...mechanismStrengthDraft.value }
  );
  const defaultPackages = packages.filter((item) => item.defaultSelected);
  selectedMechanismPackageIds.value = defaultPackages.map((item) => item.id);
  selectedAtomicInstrumentIds.value = defaultPackages.flatMap((item) => currentAtomicRulesForPackage(item).map((rule) => rule.id));
  expandedMechanismPackageIds.value = selectedMechanismPackageIds.value.slice(0, 1);
  selectedPolicyInstrumentId.value = selectedAtomicInstrumentIds.value[0] || currentAtomicRulesForPackage(packages[0])[0]?.id || "";
  policyInterventionMapMode.value = "package";
  expandedPolicyModuleId.value = "";
  selectedPolicyExperimentId.value = "S1";
  const objective = getPolicyExperimentQuestion(policy);
  policyExperimentQuestionDraft.value = objective;
  policyExperimentAppliedObjective.value = objective;
  policyExperimentAppliedPlan.value = "";
  policyExperimentDesignStage.value = "question";
  policyExperimentPresetOpen.value = false;
  policyExperimentCandidateDrafts.value = [];
  policyExperimentConfirmedBlueprints.value = [];
  initializedMechanismPolicyId.value = policy?.id || "";
}

function currentAtomicRulesForPackage(item, strength = mechanismStrengthDraft.value[item?.id] || item?.defaultStrength || "medium") {
  if (!item) return [];
  const level = item.levels[strength] || item.levels.medium || item.levels.weak;
  return level?.rules || [];
}

function syncSelectedMechanismPackagesFromAtomic(nextIds = selectedAtomicInstrumentIds.value) {
  const selectedIds = new Set(nextIds);
  selectedMechanismPackageIds.value = activeMechanismPackages.value
    .filter((item) => currentAtomicRulesForPackage(item).some((rule) => selectedIds.has(rule.id)))
    .map((item) => item.id);
}

function toggleAtomicInstrument(ruleId) {
  const nextIds = selectedAtomicInstrumentIds.value.includes(ruleId)
    ? selectedAtomicInstrumentIds.value.filter((id) => id !== ruleId)
    : [...selectedAtomicInstrumentIds.value, ruleId];
  selectedAtomicInstrumentIds.value = nextIds;
  syncSelectedMechanismPackagesFromAtomic(nextIds);
}

function selectAtomicRulePreview(ruleId) {
  if (!activeAtomicRuleRows.value.some((rule) => rule.id === ruleId)) return;
  selectedPolicyInstrumentId.value = ruleId;
}

function isMechanismPackageSelected(packageId) {
  return selectedMechanismPackageIds.value.includes(packageId);
}

function isMechanismPackageExpanded(packageId) {
  return expandedMechanismPackageIds.value.includes(packageId);
}

function toggleMechanismPackageExpanded(packageId) {
  if (isMechanismPackageExpanded(packageId)) {
    expandedMechanismPackageIds.value = expandedMechanismPackageIds.value.filter((item) => item !== packageId);
    return;
  }
  expandedMechanismPackageIds.value = [...expandedMechanismPackageIds.value, packageId];
}

function toggleMechanismPackage(packageId) {
  const item = activeMechanismPackages.value.find((packageItem) => packageItem.id === packageId);
  const ruleIds = currentAtomicRulesForPackage(item).map((rule) => rule.id);
  if (isMechanismPackageSelected(packageId)) {
    selectedAtomicInstrumentIds.value = selectedAtomicInstrumentIds.value.filter((id) => !ruleIds.includes(id));
    selectedMechanismPackageIds.value = selectedMechanismPackageIds.value.filter((item) => item !== packageId);
    return;
  }
  selectedAtomicInstrumentIds.value = [...new Set([...selectedAtomicInstrumentIds.value, ...ruleIds])];
  selectedMechanismPackageIds.value = [...selectedMechanismPackageIds.value, packageId];
  if (!isMechanismPackageExpanded(packageId)) {
    expandedMechanismPackageIds.value = [...expandedMechanismPackageIds.value, packageId];
  }
}

function getMechanismStrengthLabel(strength) {
  return mechanismStrengthLabelMap[strength] || strength;
}

function getMechanismPackageLevel(item) {
  const strength = mechanismStrengthDraft.value[item.id] || item.defaultStrength || "medium";
  return item.levels[strength] || item.levels.medium || item.levels.weak;
}

function getMechanismPlanRules(plan) {
  return Object.entries(plan?.packageStrengths || {}).flatMap(([packageId, strength]) => {
    const item = defaultImplementationPackages.find((packageItem) => packageItem.id === packageId);
    if (!item) return [];
    const level = item.levels[strength] || item.levels.medium || item.levels.weak;
    return (level?.rules || []).map((rule) => ({
      ...rule,
      packageId: item.id,
      packageName: item.shortName,
      strength: getMechanismStrengthLabel(strength)
    }));
  });
}

function setMechanismStrength(packageId, strength) {
  const item = activeMechanismPackages.value.find((packageItem) => packageItem.id === packageId);
  if (!item) return;
  const previousRules = currentAtomicRulesForPackage(item);
  const previousIds = previousRules.map((rule) => rule.id);
  const previousSelectedIds = previousIds.filter((id) => selectedAtomicInstrumentIds.value.includes(id));
  const wasFullySelected = previousIds.length > 0 && previousSelectedIds.length === previousIds.length;
  mechanismStrengthDraft.value = { ...mechanismStrengthDraft.value, [packageId]: strength };
  const nextRules = currentAtomicRulesForPackage(item, strength);
  const nextIds = nextRules.map((rule) => rule.id);
  const preservedIds = selectedAtomicInstrumentIds.value.filter((id) => !previousIds.includes(id) || nextIds.includes(id));
  selectedAtomicInstrumentIds.value = wasFullySelected
    ? [...new Set([...preservedIds, ...nextIds])]
    : preservedIds;
  syncSelectedMechanismPackagesFromAtomic(selectedAtomicInstrumentIds.value);
  if (!nextIds.includes(selectedPolicyInstrumentId.value)) {
    selectedPolicyInstrumentId.value = nextIds[0] || activePolicyInterventionNodes.value[0]?.id || "";
  }
}

function getAtomicRuleInputConfig(rule) {
  const numeric = rule && rule.after !== "" && Number.isFinite(Number(rule.after));
  if (!numeric) {
    return {
      type: "text",
      min: null,
      max: null,
      step: null,
      inputmode: "text"
    };
  }

  const boundedRatio = /(ratio|rate|share|probability)/i.test(rule.id || "");
  const wholeNumber =
    !boundedRatio &&
    (/(days|count|number|material|profession)/i.test(rule.id || "") || Number.isInteger(Number(rule.after)));
  return {
    type: "number",
    min: "0",
    max: boundedRatio ? "1" : null,
    step: boundedRatio ? "0.01" : wholeNumber ? "1" : "0.01",
    inputmode: "decimal"
  };
}

function clearCustomAtomicRule(ruleId) {
  if (!ruleId || !Object.prototype.hasOwnProperty.call(customAtomicRuleDraft.value, ruleId)) return;
  const nextDraft = { ...customAtomicRuleDraft.value };
  delete nextDraft[ruleId];
  customAtomicRuleDraft.value = nextDraft;
}

function setSelectedPolicyRulePreset(packageId, strength) {
  clearCustomAtomicRule(selectedPolicyInterventionNode.value?.id);
  setMechanismStrength(packageId, strength);
}

function enableSelectedPolicyRuleCustomValue() {
  const node = selectedPolicyInterventionNode.value;
  if (!node) return;
  if (!selectedPolicyRuleIsCustom.value) {
    customAtomicRuleDraft.value = {
      ...customAtomicRuleDraft.value,
      [node.id]: { after: String(node.rule.after) }
    };
  }
  nextTick(() => {
    policyCustomRuleInput.value?.focus();
    policyCustomRuleInput.value?.select();
  });
}

function updateSelectedPolicyRuleCustomValue(value) {
  const node = selectedPolicyInterventionNode.value;
  if (!node) return;
  customAtomicRuleDraft.value = {
    ...customAtomicRuleDraft.value,
    [node.id]: { after: value }
  };
}

function commitSelectedPolicyRuleCustomValue() {
  const node = selectedPolicyInterventionNode.value;
  if (!node || !selectedPolicyRuleIsCustom.value) return;
  const config = getAtomicRuleInputConfig(node.baseRule || node.rule);
  const currentValue = customAtomicRuleDraft.value[node.id]?.after;

  if (config.type !== "number") {
    const normalizedValue = String(currentValue ?? "").trim() || String(node.baseRule?.after ?? node.rule.after);
    updateSelectedPolicyRuleCustomValue(normalizedValue);
    return;
  }

  const parsedValue = Number(currentValue);
  if (!Number.isFinite(parsedValue)) {
    updateSelectedPolicyRuleCustomValue(String(node.baseRule?.after ?? node.rule.after));
    return;
  }

  const minimum = config.min === null ? parsedValue : Number(config.min);
  const maximum = config.max === null ? parsedValue : Number(config.max);
  const clampedValue = Math.min(maximum, Math.max(minimum, parsedValue));
  const normalizedValue =
    config.step === "1" ? String(Math.round(clampedValue)) : String(Number(clampedValue.toFixed(4)));
  updateSelectedPolicyRuleCustomValue(normalizedValue);
}

function applyMechanismPlan(planId) {
  const plan = mechanismCombinationPlans.find((item) => item.id === planId) || mechanismCombinationPlans[0];
  const activePackageIds = new Set(getPolicyMechanismPackages(activeMappingPolicy.value).map((item) => item.id));
  const relevantPackageStrengths = Object.fromEntries(
    Object.entries(plan.packageStrengths).filter(([packageId]) => activePackageIds.has(packageId))
  );
  selectedMechanismPlanId.value = plan.id;
  mechanismStrengthDraft.value = { ...mechanismStrengthDraft.value, ...relevantPackageStrengths };
  selectedMechanismPackageIds.value = Object.keys(relevantPackageStrengths);
  selectedAtomicInstrumentIds.value = activeMechanismPackages.value
    .filter((item) => selectedMechanismPackageIds.value.includes(item.id))
    .flatMap((item) => currentAtomicRulesForPackage(item).map((rule) => rule.id));
  selectedPolicyInstrumentId.value = selectedAtomicInstrumentIds.value[0] || "";
  if (plan.scenarioId && activeMappingPolicy.value.scenarios.some((scenario) => scenario.id === plan.scenarioId)) {
    selectedMappingScenarioId.value = plan.scenarioId;
  }
}

function selectPolicyExperimentScenario(experimentId) {
  const experiment = policyExperimentScenarios.value.find((item) => item.id === experimentId);
  if (!experiment) return;

  selectedPolicyExperimentId.value = experiment.id;
  mechanismStrengthDraft.value = { ...mechanismStrengthDraft.value, ...experiment.packageStrengths };
  selectedMechanismPackageIds.value = Object.keys(experiment.packageStrengths);
  selectedAtomicInstrumentIds.value = activeMechanismPackages.value
    .filter((item) => selectedMechanismPackageIds.value.includes(item.id))
    .flatMap((item) => currentAtomicRulesForPackage(item, experiment.packageStrengths[item.id]).map((rule) => rule.id));
  selectedPolicyInstrumentId.value = selectedAtomicInstrumentIds.value[0] || "";

  if (experiment.scenarioId && activeMappingPolicy.value.scenarios.some((scenario) => scenario.id === experiment.scenarioId)) {
    selectedMappingScenarioId.value = experiment.scenarioId;
  }
}

function clonePolicyExperimentCandidate(blueprint, index) {
  return {
    ...blueprint,
    packageStrengths: { ...(blueprint.packageStrengths || {}) },
    feedback: [...(blueprint.feedback || [])],
    primaryMetrics: [...(blueprint.primaryMetrics || [])],
    compareKeys: [...(blueprint.compareKeys || [])],
    included: true,
    userAdded: false,
    candidateOrder: index + 1
  };
}

function generatePolicyExperimentCandidates() {
  const objective = policyExperimentQuestionDraft.value.trim() || getPolicyExperimentQuestion(activeMappingPolicy.value);
  policyExperimentQuestionDraft.value = objective;
  policyExperimentAppliedObjective.value = objective;
  policyExperimentPresetOpen.value = false;
  policyExperimentConfirmedBlueprints.value = [];
  const blueprints = buildPolicyExperimentBlueprints(activeMappingPolicy.value, objective)
    .filter((blueprint) => blueprint.key !== "baseline")
    .slice(0, 4);
  policyExperimentCandidateDrafts.value = blueprints.map(clonePolicyExperimentCandidate);
  policyExperimentAppliedPlan.value = "";
  policyExperimentDesignStage.value = "curate";
  policyExperimentGenerationVersion.value += 1;
}

function returnToPolicyExperimentQuestion() {
  policyExperimentDesignStage.value = "question";
  policyExperimentConfirmedBlueprints.value = [];
}

function editPolicyExperimentPlans() {
  if (!policyExperimentCandidateDrafts.value.length) {
    generatePolicyExperimentCandidates();
    return;
  }
  policyExperimentConfirmedBlueprints.value = [];
  policyExperimentDesignStage.value = "curate";
}

function removePolicyExperimentCandidate(candidateKey) {
  policyExperimentCandidateDrafts.value = policyExperimentCandidateDrafts.value.filter((candidate) => candidate.key !== candidateKey);
}

function addPolicyExperimentCandidate() {
  const sequence = policyExperimentCandidateDrafts.value.length + 1;
  const policyName = policyUi(activeMappingPolicy.value?.name || "the mapped policy");
  const region = policyUi(activeMappingPolicy.value?.region || "the target region");
  const defaultPackages = activeMechanismPackages.value.filter((item) => item.defaultSelected).slice(0, 3);
  const fallbackPackages = defaultPackages.length ? defaultPackages : activeMechanismPackages.value.slice(0, 2);
  const key = `custom_${Date.now()}`;
  policyExperimentCandidateDrafts.value = [
    ...policyExperimentCandidateDrafts.value,
    {
      key,
      name: `Custom Execution Plan ${sequence}`,
      type: "Custom plan",
      tone: ["access", "network", "pilot"][sequence % 3],
      narrative: `Define an additional implementation pathway for ${policyName}.`,
      hypothesis: "State the mechanism or implementation assumption this plan is intended to test.",
      packageStrengths: Object.fromEntries(fallbackPackages.map((item) => [item.id, "medium"])),
      coverage: `${region} · user-defined scope`,
      deliveryMode: "User-defined delivery arrangement",
      enterpriseResponse: "Medium · user-defined response assumption",
      rolloutTiming: "User-defined rollout timing",
      feedback: ["User-defined behavioral response", "User-defined implementation feedback"],
      compareTo: "Custom policy comparison",
      comparisonFocus: "Additional implementation pathway requested by the user",
      resultReadout: "Measures the outcome of the user-defined execution plan against the common baseline.",
      decisionUse: "Use to test an implementation pathway that is not represented by the generated candidates.",
      primaryMetrics: [...(policyScenarioResearchFocus.value?.metrics || [])],
      guardrail: "Record every custom assumption before simulation handoff.",
      compareKeys: ["baseline"],
      included: true,
      userAdded: true,
      candidateOrder: sequence
    }
  ];
}

function confirmPolicyExperimentCandidates() {
  const selectedCandidates = policyExperimentCandidateDrafts.value
    .map((candidate, index) => ({
      ...candidate,
      name: String(candidate.name || "").trim() || `Execution Plan ${index + 1}`,
      narrative: String(candidate.narrative || "").trim() || "User-defined policy execution pathway."
    }));
  if (!selectedCandidates.length) return;
  const planDraft = selectedCandidates
    .map((candidate, index) => `${index + 1}. ${candidate.name}: ${candidate.narrative}`)
    .join(" ");
  const objective = policyExperimentQuestionDraft.value.trim() || getPolicyExperimentQuestion(activeMappingPolicy.value);
  const focus = inferPolicyScenarioResearchFocus(objective, activeMappingPolicy.value);
  const baseline = buildPolicyExperimentBlueprints(activeMappingPolicy.value, objective).find((blueprint) => blueprint.key === "baseline");
  if (!baseline) return;
  const confirmedCandidates = selectedCandidates.map((candidate) => {
    const { included, userAdded, candidateOrder, ...blueprint } = candidate;
    return {
      ...blueprint,
      packageStrengths: { ...(candidate.packageStrengths || {}) },
      feedback: [...(candidate.feedback || [])],
      primaryMetrics: [...(candidate.primaryMetrics || [])],
      compareKeys: [...(candidate.compareKeys || [])]
    };
  });
  policyExperimentAppliedObjective.value = objective;
  policyExperimentAppliedPlan.value = planDraft;
  policyExperimentConfirmedBlueprints.value = finalizePolicyExperimentBlueprints([baseline, ...confirmedCandidates], focus);
  policyExperimentDesignStage.value = "generated";
  selectedPolicyExperimentId.value = "S1";
  nextTick(() => {
    document.querySelector(".policy-experiment-grid")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function regeneratePolicyExperimentSuite() {
  generatePolicyExperimentCandidates();
}

function openMappingTab(tabKey, options = {}) {
  if (
    tabKey === "rules" &&
    initializedMechanismPolicyId.value !== activeMappingPolicy.value?.id
  ) {
    resetMechanismDraftForPolicy(activeMappingPolicy.value);
  }
  policyMappingTab.value = tabKey;
  policyMappingWorkflowStep.value = ({
    library: "text",
    detail: "mechanism",
    wizard: "text",
    scenarios: "scenario",
    rules: "rules"
  })[tabKey] || policyMappingWorkflowStep.value;
  if (options.syncUrl !== false) syncRouteToUrl();
}

function openMappingWorkflowStep(stepKey, options = {}) {
  const normalizedStepKey = stepKey === "macro" ? "mechanism" : stepKey;
  if (normalizedStepKey === "review" && !policyExperimentConfirmedBlueprints.value.length) {
    policyMappingWorkflowStep.value = "scenario";
    policyMappingTab.value = "scenarios";
    policyExperimentDesignStage.value = policyExperimentCandidateDrafts.value.length ? "curate" : "question";
    if (options.syncUrl !== false) syncRouteToUrl();
    return;
  }
  if (
    ["mechanism", "scenario", "review", "rules"].includes(normalizedStepKey) &&
    initializedMechanismPolicyId.value !== activeMappingPolicy.value?.id
  ) {
    resetMechanismDraftForPolicy(activeMappingPolicy.value);
  }
  policyMappingWorkflowStep.value = normalizedStepKey;
  policyMappingTab.value = ({
    text: "library",
    mechanism: "detail",
    scenario: "scenarios",
    review: "scenarios",
    rules: "rules"
  })[normalizedStepKey] || "library";
  if (["scenario", "review", "rules"].includes(normalizedStepKey) && selectedPolicyExperiment.value) {
    selectPolicyExperimentScenario(selectedPolicyExperiment.value.id);
  }
  if (options.syncUrl !== false) syncRouteToUrl();
}

function buildDraftAgent(aiGenerated = false, overrides = {}) {
  const roles = aiGenerated
    ? ["Contractor", "Architect", "Supplier", "Consultant", "Owner"]
    : ["Contractor"];
  const regions = ["Shenzhen", "Guangzhou", "Hong Kong", "Macau", "Zhuhai", "Foshan"];
  const role = overrides.role || roles[(locallyCreatedAgents.value.length + backendAgents.value.length) % roles.length];
  const region = overrides.region || regions[(locallyCreatedAgents.value.length * 2 + backendAgents.value.length) % regions.length];
  const serial = String(displayAgentTotal.value + 1).padStart(2, "0");
  const agentId = `${aiGenerated ? "AI" : "NEW"}-${Date.now().toString(36)}-${serial}`;
  return {
    agent_id: agentId,
    name: aiGenerated ? `${region} ${role} AI ${serial}` : `New ${region} ${role} ${serial}`,
    role,
    region,
    status: "active",
    ai_generated: aiGenerated,
    rating: aiGenerated ? 4.3 : 4.1,
    project_count: aiGenerated ? 0 : 1,
    projects: aiGenerated ? 0 : 1,
    tags: aiGenerated ? ["AI-generated", "Simulation Ready"] : ["User-created", "Draft"],
    short_description: aiGenerated
      ? "AI-generated enterprise agent prepared for simulation scenario configuration."
      : "User-created enterprise agent ready for profile editing and simulation assignment.",
    enterprise_scale: aiGenerated ? "Virtual" : "Real",
    financial_capacity: aiGenerated ? 0.68 : 0.58,
    technical_capability: aiGenerated ? 0.72 : 0.60,
    cross_region_experience: aiGenerated ? 0.66 : 0.52,
    policy_adaptability: aiGenerated ? 0.74 : 0.55,
    management_capability: aiGenerated ? 0.70 : 0.58,
    established_year: aiGenerated ? 2026 : 2025,
    employees: aiGenerated ? 1200 : 80,
    annual_revenue: aiGenerated ? 2.6 : 0.3,
    ...overrides,
    ai_generated: aiGenerated || Boolean(overrides.ai_generated)
  };
}

function openAgentModal(mode) {
  agentModalMode.value = mode;
  agentCreateSourceMode.value = "manual";
  uploadedAgentFiles.value = [];
  if (mode === "create") {
    agentForm.value = defaultAgentForm();
  } else {
    aiAgentForm.value = defaultAiAgentForm();
  }
  agentModalOpen.value = true;
}

function closeAgentModal() {
  agentModalOpen.value = false;
}

function handleAgentFiles(event) {
  const files = Array.from(event.target.files || []);
  uploadedAgentFiles.value = files.map((file) => file.webkitRelativePath || file.name);
  if (uploadedAgentFiles.value.length && !agentForm.value.name) {
    const firstName = uploadedAgentFiles.value[0].split("/").pop()?.replace(/\.(csv|xlsx|xls|json|parquet)$/i, "") || "";
    agentForm.value = {
      ...agentForm.value,
      name: firstName ? `${firstName} Agent` : agentForm.value.name,
      sourceCategory: "real_user"
    };
  }
}

function inferAiCapability(prompt, keywords, fallback) {
  const text = prompt.toLowerCase();
  const hit = keywords.some((keyword) => text.includes(keyword));
  return Math.min(0.92, Math.max(0.45, fallback + (hit ? 0.16 : 0)));
}

function createManualAgentDraft() {
  const form = agentForm.value;
  const sourceLabel = form.sourceCategory === "real_user" ? "Real user upload" : form.sourceCategory === "real_public" ? "Public registry" : "Synthetic draft";
  const fileTag = uploadedAgentFiles.value.length ? `${uploadedAgentFiles.value.length} source files` : "Manual entry";
  const activeRegions = String(form.activeRegions || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const preferredPartners = String(form.preferredPartners || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return buildDraftAgent(form.sourceCategory === "synthetic", {
    name: form.name.trim() || `${form.region} ${form.role} Agent`,
    role: form.role,
    region: form.region,
    ai_generated: false,
    data_source_type: form.sourceCategory,
    source_category: form.sourceCategory,
    source_files: uploadedAgentFiles.value,
    source_file_count: uploadedAgentFiles.value.length,
    tags: [sourceLabel, fileTag, "Validation-ready"],
    short_description: form.description || `${sourceLabel} profile configured for GBA construction simulation.`,
    description: form.description || `${form.role} configured from ${agentCreateSourceMode.value === "upload" ? "uploaded enterprise data" : "manual user input"}.`,
    enterprise_scale: form.sourceCategory === "synthetic" ? "Virtual" : "Real",
    scale: form.scale,
    ownership: form.ownership,
    enterprise_type: form.enterpriseType,
    service_scope: form.serviceScope,
    qualification_level: form.qualificationLevel,
    financial_capacity: form.financialCapacity,
    technical_capability: form.technicalCapability,
    management_capability: form.managementCapability,
    total_resource_capacity: form.totalResourceCapacity,
    risk_preference: form.riskPreference,
    collaboration_preference: form.collaborationPreference,
    cross_region_experience: form.crossRegionExperience,
    policy_adaptability: form.policyAdaptability,
    design_capability: form.designCapability,
    cost_estimation_capability: form.costEstimationCapability,
    construction_capability: form.constructionCapability,
    quality_management_capability: form.qualityManagementCapability,
    safety_management_capability: form.safetyManagementCapability,
    supervision_capability: form.supervisionCapability,
    supply_reliability: form.supplyReliability,
    material_quality: form.materialQuality,
    payment_reliability: form.paymentReliability,
    decision_speed: form.decisionSpeed,
    active_regions: activeRegions,
    preferred_partners: preferredPartners,
    project_count: uploadedAgentFiles.value.length || 1,
    projects: uploadedAgentFiles.value.length || 1,
    employees: Number(form.employees) || 0,
    annual_revenue: Number(form.annualRevenue) || 0,
    established_year: 2026,
    notes: "Created through the frontend agent configuration modal. Source category and assumptions should be validated before batch simulation export."
  });
}

function createAiAgentDraft() {
  const form = aiAgentForm.value;
  const prompt = form.prompt.trim() || `Generate a ${form.region} ${form.role} for ${form.projectFocus} and ${form.collaborationProfile} in GBA construction collaboration simulation.`;
  const financial = inferAiCapability(prompt, ["financial", "capital", "large", "scale", "fund"], 0.62);
  const technical = inferAiCapability(prompt, ["technical", "epc", "bim", "design", "engineering", "smart"], 0.66);
  const management = inferAiCapability(prompt, ["management", "delivery", "safety", "quality", "schedule"], 0.64);
  const crossRegion = inferAiCapability(prompt, ["cross", "hong kong", "macau", "regional", "bay area", "gba"], 0.58);
  const policy = inferAiCapability(prompt, ["policy", "green", "low-carbon", "sustain", "compliance", "qualification"], 0.62);
  const safety = inferAiCapability(`${prompt} ${form.collaborationProfile}`, ["safety", "risk", "site", "inspection"], 0.62);
  const quality = inferAiCapability(`${prompt} ${form.projectFocus}`, ["quality", "grade", "premium", "defect"], 0.64);
  const supply = inferAiCapability(prompt, ["supplier", "supply", "material", "inventory", "logistics"], 0.58);
  return buildDraftAgent(true, {
    name: `${form.region} ${form.role} AI Agent`,
    role: form.role,
    region: form.region,
    data_source_type: "synthetic",
    source_category: "synthetic",
    source_prompt: prompt,
    tags: ["AI-generated", "Synthetic", form.projectFocus, form.collaborationProfile],
    short_description: prompt.slice(0, 160),
    description: prompt,
    enterprise_scale: "Virtual",
    scale: "Scenario Generated",
    ownership: "Synthetic",
    enterprise_type: form.role,
    service_scope: `${form.projectFocus}; ${form.collaborationProfile}`,
    qualification_level: Math.min(0.92, technical + 0.04),
    total_resource_capacity: Math.min(0.9, management + 0.08),
    risk_preference: form.collaborationProfile.includes("resilience") ? 0.46 : 0.58,
    collaboration_preference: Math.min(0.9, crossRegion + 0.12),
    financial_capacity: financial,
    technical_capability: technical,
    management_capability: management,
    cross_region_experience: crossRegion,
    policy_adaptability: policy,
    design_capability: inferAiCapability(prompt, ["design", "architect", "bim"], 0.52),
    cost_estimation_capability: inferAiCapability(prompt, ["cost", "qs", "claim", "budget"], 0.54),
    construction_capability: inferAiCapability(prompt, ["contractor", "epc", "construction", "delivery"], 0.68),
    quality_management_capability: quality,
    safety_management_capability: safety,
    supervision_capability: inferAiCapability(prompt, ["supervision", "inspection", "engineer"], 0.52),
    supply_reliability: supply,
    material_quality: inferAiCapability(prompt, ["green", "material", "low-carbon", "prefabrication"], 0.58),
    payment_reliability: financial,
    decision_speed: inferAiCapability(prompt, ["fast", "agile", "rapid", "responsive"], 0.62),
    active_regions: [form.region],
    preferred_partners: [form.collaborationProfile],
    project_count: 0,
    projects: 0,
    employees: 1200,
    annual_revenue: 2.6,
    established_year: 2026,
    notes: "AI-generated synthetic agent. Do not treat as a real enterprise record; assumptions should be included in methodology and validation outputs."
  });
}

async function persistCreatedAgent(draft) {
  agentLoading.value = true;
  agentPage.value = 1;
  enterpriseTypeFilter.value = "All";
  enterpriseRegionFilter.value = "All Regions";
  agentKeyword.value = "";
  try {
    if (!backendOnline.value) throw new Error("Backend unavailable");
    const created = await agentApi.create(draft);
    const normalized = { ...draft, ...created };
    backendAgents.value = [normalized, ...backendAgents.value.filter((agent) => agent.agent_id !== normalized.agent_id)];
    agentTotal.value = Math.max(agentTotal.value + 1, backendAgents.value.length);
    selectedAgentId.value = normalized.agent_id;
  } catch (error) {
    locallyCreatedAgents.value = [draft, ...locallyCreatedAgents.value.filter((agent) => agent.agent_id !== draft.agent_id)];
    selectedAgentId.value = draft.agent_id;
    console.warn("Agent creation used local fallback data.", error);
  } finally {
    agentLoading.value = false;
    nextTick(renderCharts);
  }
}

async function submitAgentModal() {
  const draft = agentModalMode.value === "ai" ? createAiAgentDraft() : createManualAgentDraft();
  await persistCreatedAgent(draft);
  closeAgentModal();
}

function setEnterpriseTypeFilter(type) {
  if (enterpriseTypeFilter.value === type) return;
  enterpriseTypeFilter.value = type;
  agentPage.value = 1;
}

async function goAgentPage(delta) {
  const nextPage = Math.min(agentTotalPages.value, Math.max(1, agentPage.value + delta));
  if (nextPage === agentPage.value) return;
  agentPage.value = nextPage;
  await loadAgentPage();
}

async function loadSelectedAgentProfile() {
  if (!selectedAgentId.value || agentProfiles.value[selectedAgentId.value] || !backendOnline.value) return;
  try {
    const profile = await agentApi.get(selectedAgentId.value);
    agentProfiles.value = { ...agentProfiles.value, [selectedAgentId.value]: profile };
  } catch (error) {
    console.warn("Agent profile loading failed.", error);
  }
}

async function loadSelectedAgentCognitiveState() {
  if (!selectedAgentId.value || agentCognitiveStates.value[selectedAgentId.value] || !backendOnline.value) return;
  agentCognitiveLoading.value = true;
  try {
    const cognitiveState = await agentApi.cognitiveState(selectedAgentId.value);
    agentCognitiveStates.value = { ...agentCognitiveStates.value, [selectedAgentId.value]: cognitiveState };
  } catch (error) {
    console.warn("Agent cognitive state loading failed.", error);
  } finally {
    agentCognitiveLoading.value = false;
  }
}

async function selectAgentDetailTab(tabKey) {
  agentDetailTab.value = tabKey;
  if (tabKey !== "profile") {
    await loadSelectedAgentCognitiveState();
  }
}

function humanizeKey(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function percent(value) {
  const numeric = Number(value || 0);
  return `${Math.round(numeric * 100)}%`;
}

function strategyMetrics(strategy = {}) {
  return [
    ["bidding_aggressiveness", "Bidding aggressiveness"],
    ["margin_protection_level", "Margin protection"],
    ["cooperation_preference", "Cooperation"],
    ["risk_tolerance", "Risk tolerance"],
    ["regional_expansion_preference", "Regional expansion"],
    ["cash_preservation_level", "Cash preservation"]
  ].map(([key, label]) => ({ key, label, value: Number(strategy[key] || 0) }));
}

async function loadSelectedClusterDetail() {
  const clusterId = activeCluster.value?.id;
  if (!clusterId || clusterDetails.value[clusterId] || !backendOnline.value) return;
  try {
    const detail = await clusterApi.get(clusterId);
    clusterDetails.value = { ...clusterDetails.value, [clusterId]: detail };
  } catch (error) {
    console.warn("Cluster detail loading failed.", error);
  }
}

async function loadSelectedPolicyDetail() {
  const policyId = activePolicy.value?.id;
  if (!policyId || !backendOnline.value) return;
  try {
    const [detail, preview] = await Promise.all([policyApi.get(policyId), policyApi.preview(policyId)]);
    policyDetails.value = { ...policyDetails.value, [policyId]: detail };
    policyPreview.value = preview;
  } catch (error) {
    console.warn("Policy detail loading failed.", error);
  }
}

async function sendQuickPrompt(message) {
  chatInput.value = message;
  await sendChatMessage();
}

async function sendChatMessage() {
  const message = chatInput.value.trim();
  if (!message || chatLoading.value) return;
  chatMessages.value = [...chatMessages.value, { sender: "user", text: message }];
  chatInput.value = "";
  chatLoading.value = true;
  try {
    const response = await agentApi.chat(selectedAgentId.value, message, {
      policy_id: activePolicy.value?.id || null,
      simulation_id: simulationId.value || null
    });
    chatMessages.value = [...chatMessages.value, { sender: "agent", text: response.reply }];
  } catch {
    chatMessages.value = [
      ...chatMessages.value,
      {
        sender: "agent",
        text: `${selectedAgent.value.name} is available, but the backend chat endpoint is currently unreachable.`
      }
    ];
  } finally {
    chatLoading.value = false;
  }
}

function stopPlayback() {
  simulationPlaying.value = false;
  if (playbackTimer) {
    window.clearInterval(playbackTimer);
    playbackTimer = null;
  }
}

function startPlaybackTimer() {
  if (playbackTimer) window.clearInterval(playbackTimer);
  playbackTimer = window.setInterval(advancePlayback, playbackIntervalMs.value);
}

async function togglePlayback() {
  if (simulationPlaying.value) {
    stopPlayback();
    return;
  }
  if (!simulationId.value) return;
  if (currentPlaybackTick.value >= playbackMaxTick.value) {
    currentPlaybackTick.value = 1;
    await loadRuntimeAtTick(1);
  }
  simulationPlaying.value = true;
  startPlaybackTimer();
}

async function advancePlayback() {
  if (playbackRequestInFlight) return;
  const nextTickValue = Math.min(playbackMaxTick.value, Number(currentPlaybackTick.value || 1) + 1);
  if (nextTickValue === currentPlaybackTick.value || nextTickValue >= playbackMaxTick.value) {
    await loadRuntimeAtTick(nextTickValue);
    stopPlayback();
    return;
  }
  await loadRuntimeAtTick(nextTickValue);
}

async function stepPlayback(delta = 1) {
  stopPlayback();
  const targetTick = Math.max(1, Math.min(playbackMaxTick.value, Number(currentPlaybackTick.value || 1) + delta));
  await loadRuntimeAtTick(targetTick);
}

async function seekPlaybackTick() {
  stopPlayback();
  await loadRuntimeAtTick(Number(currentPlaybackTick.value || 1));
}

async function loadRuntimeAtTick(tick) {
  if (!simulationId.value) return;
  playbackRequestInFlight = true;
  try {
    const targetTick = Math.max(1, Math.min(playbackMaxTick.value, Number(tick) || 1));
    const runtime = await simulationApi.runtimeState(simulationId.value, targetTick);
    runtimeState.value = runtime;
    currentPlaybackTick.value = runtime.current_tick || targetTick;
    simulationResult.value = runtimeToLegacyResult(runtime);
    await maybeSelectDefaultRuntimeEnterprise(runtime);
    await refreshSelectedEnterpriseHistory(currentPlaybackTick.value);
    await nextTick();
    renderRuntimeMap();
  } catch (error) {
    console.warn("Runtime tick loading failed.", error);
  } finally {
    playbackRequestInFlight = false;
  }
}

async function openEnterpriseHistory(node) {
  selectedRuntimeProject.value = null;
  selectedRuntimeEnterprise.value = node;
  selectedEnterpriseHistory.value = null;
  enterpriseActivityExpanded.value = false;
  if (!simulationId.value || !node?.id) return;
  enterpriseHistoryLoading.value = true;
  try {
    selectedEnterpriseHistory.value = await simulationApi.agentHistory(
      simulationId.value,
      node.id,
      Number(currentPlaybackTick.value || runtimeState.value?.current_tick || 1)
    );
  } catch (error) {
    console.warn("Agent history loading failed.", error);
  } finally {
    enterpriseHistoryLoading.value = false;
  }
}

async function refreshSelectedEnterpriseHistory(tick = currentPlaybackTick.value) {
  if (!simulationId.value || !selectedRuntimeEnterprise.value?.id) return;
  try {
    selectedEnterpriseHistory.value = await simulationApi.agentHistory(
      simulationId.value,
      selectedRuntimeEnterprise.value.id,
      Number(tick || runtimeState.value?.current_tick || 1)
    );
  } catch (error) {
    console.warn("Agent history refresh failed.", error);
  }
}

function openProjectDetails(project) {
  selectedRuntimeProject.value = project;
  selectedRuntimeEnterprise.value = null;
  selectedEnterpriseHistory.value = null;
  enterpriseActivityExpanded.value = false;
  expandedProjectEventIds.value = new Set();
  defaultEnterpriseSelectionLocked.value = true;
}

function closeRuntimeSelection() {
  defaultEnterpriseSelectionLocked.value = true;
  selectedRuntimeProject.value = null;
  selectedRuntimeEnterprise.value = null;
  selectedEnterpriseHistory.value = null;
  enterpriseActivityExpanded.value = false;
  expandedProjectEventIds.value = new Set();
}

function closeEnterpriseHistory() {
  closeRuntimeSelection();
}

async function maybeSelectDefaultRuntimeEnterprise(runtime) {
  if (selectedRuntimeProject.value?.projectId) {
    const project = runtime?.map?.projects?.find((item) => item.project_id === selectedRuntimeProject.value.projectId);
    if (project) {
      selectedRuntimeProject.value = {
        ...selectedRuntimeProject.value,
        progress: Math.round(project.progress || 0),
        quality: Number(project.quality_score || 0),
        delayDays: Number(project.delay_days || 0),
        costOverrun: Number(project.cost_overrun_ratio || 0),
        status: project.status,
        stage: project.stage,
        stageLabel: statusLabel(project.stage || project.status || "project"),
        createdTick: normalizeProjectCreatedTick(project)
      };
    }
  }
}

function isEventForProject(event, projectId, projectName) {
  const explicitProjectId = String(event?.project_id || event?.data?.project_id || "").toLowerCase();
  if (projectId && explicitProjectId === projectId) return true;
  const searchable = [
    event?.project_id,
    event?.data?.project_id,
    event?.data?.project_name,
    event?.description,
    event?.title
  ].map((value) => String(value || "").toLowerCase()).join(" ");
  return Boolean(
    (projectId && searchable.includes(projectId)) ||
    (projectName && projectName.length > 2 && searchable.includes(projectName))
  );
}

function isProjectLifecycleEvent(event) {
  const type = String(event?.event_type || "").toLowerCase();
  return new Set([
    "project_initiated",
    "project_opportunity_initiated",
    "consultant_team_appointed",
    "design_started",
    "design_submitted",
    "approval_submitted",
    "approval_approved",
    "approval_rejected",
    "tender_preparation",
    "tender_documents_prepared",
    "tender_opened",
    "tendering",
    "bid_evaluation",
    "bid_evaluation_completed",
    "contract_awarded",
    "supplier_selected",
    "construction_started",
    "construction_progress",
    "completion",
    "project_completed",
    "final_account",
    "variation_requested",
    "quality_issue",
    "safety_issue",
    "supply_delay"
  ]).has(type);
}

function projectLifecycleRank(project) {
  const stage = String(project?.stage || project?.status || "").toLowerCase();
  const progress = Number(project?.progress || 0);
  let rank = 1;
  if (/approval/.test(stage)) rank = 2;
  if (/tender_preparation/.test(stage)) rank = 3;
  if (/tendering/.test(stage)) rank = 4;
  if (/bid_evaluation/.test(stage)) rank = 5;
  if (/contract_award|mobilization/.test(stage)) rank = 6;
  if (/construction|building|ongoing/.test(stage)) rank = 7;
  if (/completion|handover/.test(stage)) rank = 8;
  if (/final_account|closed|completed/.test(stage)) rank = 9;
  if (progress > 0) rank = Math.max(rank, 7);
  if (progress >= 98) rank = Math.max(rank, 8);
  return rank;
}

function normalizeProjectCreatedTick(project) {
  const rawTick =
    project?.createdTick ??
    project?.created_tick ??
    project?.createdAtTick ??
    project?.created_at_tick ??
    project?.initiatedTick ??
    project?.initiated_tick ??
    project?.flags?.created_tick;
  const tick = Number(rawTick);
  return Number.isFinite(tick) && tick > 0 ? Math.round(tick) : 1;
}

function milestoneTick(currentTick, fraction, minimumOffset = 1, startTick = 1) {
  const start = Math.max(1, Number(startTick || 1));
  const end = Math.max(start, Number(currentTick || start));
  const span = Math.max(1, end - start);
  const offset = Math.max(minimumOffset, Math.round(span * fraction));
  return Math.max(start, Math.min(end, start + offset));
}

function projectLifecycleDisplayTick(project) {
  const createdTick = normalizeProjectCreatedTick(project);
  const playbackTick = Number(currentPlaybackTick.value || currentTimelinePoint.value?.tick || playbackMaxTick.value || createdTick);
  const progress = Math.max(0, Math.min(100, Math.round(Number(project?.progress || 0))));
  const duration = Number(project?.plannedDuration || project?.planned_duration || 60);
  const estimatedTick = progress > 0
    ? createdTick + Math.max(1, Math.round((progress / 100) * Math.max(1, duration)))
    : createdTick;
  return Math.max(createdTick, playbackTick, estimatedTick);
}

function projectStageDisplayName(project) {
  const raw = String(project?.stage || project?.status || "current stage").toLowerCase();
  if (["ongoing", "building", "active"].includes(raw)) return "construction delivery";
  return statusLabel(raw);
}

function projectLifecycleMilestones(project) {
  const createdTick = normalizeProjectCreatedTick(project);
  const currentTick = projectLifecycleDisplayTick(project);
  const progress = Math.max(0, Math.min(100, Math.round(Number(project?.progress || 0))));
  const city = project?.city || "the selected region";
  const stage = projectStageDisplayName(project).toLowerCase();
  const rank = projectLifecycleRank(project);
  const projectId = project?.projectId || "selected-project";
  const milestones = [
    {
      rank: 1,
      event_id: `${projectId}-milestone-initiation`,
      tick: createdTick,
      event_type: "project_initiated",
      description: `The owner initiated the project in ${city} and confirmed the initial scope, budget, and regional location.`
    },
    {
      rank: 1,
      event_id: `${projectId}-milestone-design`,
      tick: milestoneTick(currentTick, 0.08, 0, createdTick),
      event_type: "design_started",
      description: "Architect and QS support started design development, cost planning, and information coordination."
    },
    {
      rank: 2,
      event_id: `${projectId}-milestone-approval`,
      tick: milestoneTick(currentTick, 0.18, 2, createdTick),
      event_type: "approval_approved",
      description: "Government approval review cleared the submission, allowing procurement and tender preparation to proceed."
    },
    {
      rank: 3,
      event_id: `${projectId}-milestone-tender-prep`,
      tick: milestoneTick(currentTick, 0.28, 2, createdTick),
      event_type: "tender_preparation",
      description: "QS prepared tender documents, bill of quantities, and evaluation criteria for contractor selection."
    },
    {
      rank: 4,
      event_id: `${projectId}-milestone-tendering`,
      tick: milestoneTick(currentTick, 0.36, 2, createdTick),
      event_type: "tender_opened",
      description: "Tendering opened and qualified contractors were invited to evaluate the opportunity and submit bids."
    },
    {
      rank: 5,
      event_id: `${projectId}-milestone-bid-evaluation`,
      tick: milestoneTick(currentTick, 0.44, 3, createdTick),
      event_type: "bid_evaluation",
      description: "Owner and QS evaluated submitted bids by price, capability, compliance, and project delivery fit."
    },
    {
      rank: 6,
      event_id: `${projectId}-milestone-contract`,
      tick: milestoneTick(currentTick, 0.52, 3, createdTick),
      event_type: "contract_awarded",
      description: "The preferred contractor was awarded the contract and became active for mobilization and delivery."
    },
    {
      rank: 7,
      event_id: `${projectId}-milestone-construction`,
      tick: currentTick,
      event_type: "construction_progress",
      description: progress > 0
        ? `Construction is in ${stage}, with project progress at ${progress}%.`
        : "Construction has started and monthly performance updates are being tracked."
    },
    {
      rank: 8,
      event_id: `${projectId}-milestone-completion`,
      tick: currentTick,
      event_type: "project_completed",
      description: "Completion inspection and handover checks were triggered after construction reached the target progress."
    },
    {
      rank: 9,
      event_id: `${projectId}-milestone-final-account`,
      tick: currentTick,
      event_type: "final_account",
      description: "Final account settlement closed the commercial cycle and released remaining contractual obligations."
    }
  ];
  return milestones.filter((event) => event.rank <= rank).map(({ rank: _rank, ...event }) => event);
}

function dedupeProjectEvents(events) {
  const seen = new Set();
  return events.filter((event) => {
    const key = projectEventCategory(event);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function projectEventCategory(event) {
  const type = String(event?.event_type || "").toLowerCase();
  if (["project_initiated", "project_opportunity_initiated"].includes(type)) return "initiation";
  if (["consultant_team_appointed"].includes(type)) return "consultant_selection";
  if (["design_started", "design_submitted"].includes(type)) return "design";
  if (["approval_submitted", "approval_approved", "approval_rejected"].includes(type)) return "approval";
  if (["tender_preparation", "tender_documents_prepared"].includes(type)) return "tender_preparation";
  if (["tender_opened", "tendering"].includes(type)) return "tendering";
  if (["bid_evaluation", "bid_evaluation_completed"].includes(type)) return "bid_evaluation";
  if (["contract_awarded"].includes(type)) return "contract_award";
  if (["supplier_selected"].includes(type)) return "supplier_selection";
  if (["construction_started", "construction_progress", "construction_progress_updated"].includes(type)) return "construction";
  if (["completion", "project_completed"].includes(type)) return "completion";
  if (["final_account"].includes(type)) return "final_account";
  return `${type}-${Number(event?.tick || 0)}`;
}

function projectEventTypeLabel(type) {
  const normalized = String(type || "event").toLowerCase();
  const labels = {
    project_initiated: "Project Initiated",
    project_opportunity_initiated: "Project Initiated",
    consultant_team_appointed: "Consultants Appointed",
    design_started: "Design Started",
    design_submitted: "Design Submitted",
    approval_submitted: "Approval Submitted",
    approval_approved: "Approval Approved",
    approval_rejected: "Approval Returned",
    tender_preparation: "Tender Preparation",
    tender_documents_prepared: "Tender Documents Ready",
    tender_opened: "Tender Opened",
    tendering: "Tendering",
    bid_submitted: "Bid Submitted",
    bid_evaluation: "Bid Evaluation",
    bid_evaluation_completed: "Preferred Bidder Selected",
    contract_awarded: "Contract Awarded",
    supplier_selected: "Supplier Appointed",
    construction_started: "Construction Started",
    construction_progress: "Construction Progress",
    construction_progress_updated: "Construction Progress",
    completion: "Completion Check",
    project_completed: "Completion Check",
    final_account: "Final Account",
    variation_requested: "Design Variation",
    quality_issue: "Quality Review",
    safety_issue: "Safety Review",
    supply_delay: "Supply Delay"
  };
  return labels[normalized] || eventTypeLabel(type);
}

function sanitizeProjectEventDescription(description) {
  return sanitizeEventDescription(description)
    .replace(/\bP(?:GEN)?\d+\b/gi, "this project")
    .replace(/\bSIM[A-Z0-9]+\b/g, "the simulation")
    .replace(/\s+/g, " ")
    .trim();
}

function friendlyProjectEventDescription(event, project) {
  const type = String(event?.event_type || "").toLowerCase();
  const description = String(event?.description || "");
  if (description && String(event?.event_id || "").includes("-milestone-")) return description;
  if (type === "stage_transition") {
    return `The project passed a lifecycle gate and entered ${statusLabel(project?.stage || project?.status || "the next stage").toLowerCase()}.`;
  }
  if (type === "project_opportunity_initiated") {
    const score = event?.data?.decision_score;
    return `The owner decided to launch this project after checking market demand, financing capacity, and available resources${score ? `; decision score ${Math.round(Number(score) * 100)}%.` : "."}`;
  }
  if (type === "consultant_team_appointed") {
    return "The owner appointed the design and cost consultant team before design work started.";
  }
  if (type === "tender_documents_prepared") {
    return "QS prepared the tender package, bill of quantities, and contractor evaluation criteria.";
  }
  if (type === "tender_opened") {
    const invited = event?.data?.invited_count || event?.data?.invited_contractors?.length;
    return invited ? `${invited} qualified contractors were invited to review the project and decide whether to bid.` : "Qualified contractors were invited to review the project and decide whether to bid.";
  }
  if (type === "bid_submitted") {
    return "A contractor submitted a bid during tendering for this project.";
  }
  if (type === "bid_evaluation_completed") {
    const winner = event?.data?.selected_contractor_name || projectAgentNameById(event?.data?.selected_contractor_id, "the preferred contractor");
    return `Owner and QS completed bid evaluation and selected ${winner} as preferred bidder.`;
  }
  if (type === "contract_awarded") {
    return "Contract award confirmed the selected contractor and commercial terms for delivery.";
  }
  if (type === "supplier_selected") {
    const supplier = event?.data?.supplier_name || projectAgentNameById(event?.data?.supplier_id, "a supplier");
    return `The selected contractor appointed ${supplier} for construction supply.`;
  }
  if (type === "construction_progress_updated" || type === "construction_progress") {
    return `Construction progress is now ${Math.round(Number(project?.progress || 0))}% and performance tracking is active.`;
  }
  if (type === "project_completed" || type === "completion") {
    return "Completion inspection, handover checks, and close-out preparation were recorded for this project.";
  }
  if (type === "final_account") {
    return "Final account settlement closed the remaining commercial obligations.";
  }
  return sanitizeProjectEventDescription(description) || "A project lifecycle milestone was recorded.";
}

function toggleProjectEventDetails(eventId) {
  const nextIds = new Set(expandedProjectEventIds.value);
  if (nextIds.has(eventId)) {
    nextIds.delete(eventId);
  } else {
    nextIds.add(eventId);
  }
  expandedProjectEventIds.value = nextIds;
}

function isProjectEventExpanded(eventId) {
  return expandedProjectEventIds.value.has(eventId);
}

function projectAgentNameById(agentId, fallback = "Not selected yet") {
  if (!agentId) return fallback;
  const id = String(agentId);
  const participant = selectedProjectParticipants.value.find((item) => item.id === id);
  if (participant?.name) return participant.name;
  const enterprise = runtimeMapEnterprises.value.find((item) => item.nodeId === id || item.node?.id === id);
  if (enterprise?.node?.name || enterprise?.name) {
    return formatEnterpriseDisplayName(enterprise.node?.name || enterprise.name, fallback);
  }
  return id;
}

function projectRoleName(project, role, fallback) {
  const normalized = String(role || "").toLowerCase();
  const participant = selectedProjectParticipants.value.find((item) => String(item.role || "").toLowerCase().includes(normalized));
  return participant?.name || fallback;
}

function projectSupplierNames(project) {
  const ids = project?.selectedSupplierIds || project?.selected_supplier_ids || [];
  if (!ids.length) return "Supplier not confirmed yet";
  return ids.map((id) => projectAgentNameById(id, id)).join(", ");
}

function formatProjectMoney(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) return "Not confirmed";
  if (amount >= 100000000) return `¥${(amount / 100000000).toFixed(2)}亿`;
  if (amount >= 10000) return `¥${(amount / 10000).toFixed(0)}万`;
  return `¥${amount.toLocaleString()}`;
}

function bidRowsForProject(project) {
  const bids = [
    ...(project?.bids || []),
    ...((project?.contracts || []).map((contract) => ({
      contractor_id: contract.contractor_id,
      bid_price: contract.contract_sum,
      result: "Awarded"
    })))
  ];
  const seen = new Set();
  return bids
    .filter((bid) => bid?.contractor_id && !seen.has(bid.contractor_id) && seen.add(bid.contractor_id))
    .slice(0, 6);
}

function projectEventDetailRows(event, project) {
  const type = String(event?.event_type || "").toLowerCase();
  const data = event?.data || {};
  const ownerName = projectAgentNameById(project?.ownerId || data.owner_id, "Project owner");
  const qsName = projectAgentNameById(project?.selectedQsId || data.qs_id, projectRoleName(project, "qs", "QS team"));
  const architectName = projectAgentNameById(project?.selectedArchitectId || data.architect_id, projectRoleName(project, "architect", "Architect team"));
  const contractorName = projectAgentNameById(
    data.selected_contractor_id || data.contractor_id || project?.selectedContractorId,
    data.selected_contractor_name || data.contractor_name || "Contractor not selected yet"
  );
  const supplierName = projectAgentNameById(
    data.supplier_id || project?.selectedSupplierIds?.[0],
    data.supplier_name || "Supplier not confirmed yet"
  );
  const governmentName = data.reviewer_name || projectRoleName(project, "government", "GBA Regulator");
  const invitedCount = Number(data.invited_count || data.invited_contractors?.length || 0);
  const rankedBidCount = Number(data.valid_bid_count || data.ranked_bids?.length || data.bids?.length || 0);
  const bidCount = Math.max(rankedBidCount, bidRowsForProject(project).length);
  const rowsByType = {
    project_initiated: [
      { label: "Initiated by", value: ownerName },
      { label: "Project location", value: project?.city || "GBA" },
      { label: "Initial budget", value: formatProjectMoney(project?.initialBudget) },
      { label: "Planned duration", value: project?.plannedDuration ? `${project.plannedDuration} months` : "Pending feasibility" }
    ],
    project_opportunity_initiated: [
      { label: "Initiated by", value: ownerName },
      { label: "Project location", value: project?.city || "GBA" },
      { label: "Initial budget", value: formatProjectMoney(project?.initialBudget) },
      { label: "Decision basis", value: data.decision_score ? `Owner readiness ${Math.round(Number(data.decision_score) * 100)}%` : "Owner resources, market demand, financing, and policy conditions" }
    ],
    consultant_team_appointed: [
      { label: "Owner", value: data.owner_name || ownerName },
      { label: "Architect", value: data.architect_name || architectName },
      { label: "QS", value: data.qs_name || qsName },
      { label: "Selection basis", value: (data.selection_basis || []).slice(0, 3).map(statusLabel).join(", ") || "Capability, region, collaboration prior, and available resources" }
    ],
    design_started: [
      { label: "Design lead", value: architectName },
      { label: "Cost planning", value: qsName },
      { label: "Owner approval", value: ownerName },
      { label: "Design objective", value: "Improve design quality and tender information completeness" }
    ],
    approval_approved: [
      { label: "Reviewed by", value: governmentName },
      { label: "Review result", value: data.result ? statusLabel(data.result) : "Approved" },
      { label: "Approval confidence", value: data.approval_probability ? `${Math.round(Number(data.approval_probability) * 100)}%` : "Policy and information checks passed" },
      { label: "Next action", value: "Proceed to tender preparation" }
    ],
    approval_rejected: [
      { label: "Reviewed by", value: governmentName },
      { label: "Review result", value: data.result ? statusLabel(data.result) : "Revision required" },
      { label: "Returned to", value: "Design revision and resubmission" }
    ],
    tender_preparation: [
      { label: "Prepared by", value: qsName },
      { label: "Owner review", value: ownerName },
      { label: "Documents", value: "Tender document, BOQ, evaluation criteria" },
      { label: "Budget basis", value: formatProjectMoney(project?.estimatedCost || project?.initialBudget) }
    ],
    tender_documents_prepared: [
      { label: "Prepared by", value: data.qs_name || qsName },
      { label: "Information quality", value: data.information_quality ? `${Math.round(Number(data.information_quality) * 100)}%` : "Ready for tender" },
      { label: "Planned cost", value: formatProjectMoney(data.planned_cost || project?.estimatedCost || project?.initialBudget) },
      { label: "Criteria", value: (data.evaluation_criteria || []).slice(0, 4).map(statusLabel).join(", ") || "Price, capability, safety, quality, and finance" }
    ],
    tender_opened: [
      { label: "Tender issued by", value: ownerName },
      { label: "Tender manager", value: qsName },
      { label: "Invited contractors", value: invitedCount ? `${invitedCount} firms invited` : "Candidate contractors invited" },
      { label: "Tender attractiveness", value: data.tender_attractiveness ? `${Math.round(Number(data.tender_attractiveness) * 100)}%` : "Calculated from budget, risk, and policy friction" },
      { label: "Target contract value", value: formatProjectMoney(project?.initialBudget) }
    ],
    bid_evaluation: [
      { label: "Evaluated by", value: `${ownerName} + ${qsName}` },
      { label: "Valid bids", value: bidCount ? `${bidCount} bids` : "Bids being evaluated" },
      { label: "Criteria", value: "Price, technical fit, quality, safety, financial capacity" },
      { label: "Preferred bidder", value: contractorName }
    ],
    bid_evaluation_completed: [
      { label: "Evaluated by", value: `${ownerName} + ${qsName}` },
      { label: "Valid bids", value: bidCount ? `${bidCount} bids` : "No valid bid count reported" },
      { label: "Preferred bidder", value: data.selected_contractor_name || contractorName },
      { label: "Preferred bid", value: formatProjectMoney(data.contract_sum || project?.contractSum) }
    ],
    contract_awarded: [
      { label: "Awarded to", value: contractorName },
      { label: "Contract sum", value: formatProjectMoney(data.contract_sum || project?.contractSum) },
      { label: "Contract duration", value: project?.plannedDuration ? `${project.plannedDuration} months` : "Based on project schedule" },
      { label: "Supplier", value: projectSupplierNames(project) }
    ],
    supplier_selected: [
      { label: "Selected by", value: data.contractor_name || contractorName },
      { label: "Supplier", value: data.supplier_name || supplierName },
      { label: "Material quality", value: data.material_quality ? `${Math.round(Number(data.material_quality) * 100)}%` : "Not reported" },
      { label: "Supply reliability", value: data.supply_reliability ? `${Math.round(Number(data.supply_reliability) * 100)}%` : "Not reported" }
    ],
    construction_progress: [
      { label: "Main contractor", value: contractorName },
      { label: "Supplier", value: projectSupplierNames(project) },
      { label: "Current progress", value: `${Math.round(Number(project?.progress || 0))}%` },
      { label: "Quality score", value: `${Math.round(Number(project?.quality || 0))}%` },
      { label: "Delay", value: `${Number(project?.delayDays || 0)} days` }
    ],
    project_completed: [
      { label: "Completion review", value: governmentName },
      { label: "Quality result", value: `${Math.round(Number(project?.quality || 0))}%` },
      { label: "Handover status", value: "Completion and final account preparation" }
    ],
    final_account: [
      { label: "Settled by", value: `${ownerName} + ${qsName}` },
      { label: "Final payment basis", value: formatProjectMoney(project?.contractSum) },
      { label: "Release status", value: "Contractor, QS, and standby consultants released after settlement" }
    ],
    variation_requested: [
      { label: "Requested during", value: projectStageDisplayName(project) },
      { label: "Design support", value: architectName },
      { label: "Commercial review", value: qsName }
    ],
    quality_issue: [
      { label: "Reviewed by", value: governmentName },
      { label: "Result", value: "Rectification required before acceptance" },
      { label: "Responsible party", value: contractorName }
    ],
    safety_issue: [
      { label: "Reviewed by", value: governmentName },
      { label: "Result", value: "Safety risk mitigation required" },
      { label: "Responsible party", value: contractorName }
    ],
    supply_delay: [
      { label: "Supplier", value: projectSupplierNames(project) },
      { label: "Impact", value: "Material availability reduced and delay risk increased" }
    ]
  };
  return rowsByType[type] || rowsByType[projectEventCategory(event)] || [
    { label: "Project", value: project?.name || "Selected project" },
    { label: "Stage", value: projectStageDisplayName(project) }
  ];
}

function projectEventBidRows(event, project) {
  const type = String(event?.event_type || "").toLowerCase();
  if (!["tender_opened", "tendering", "bid_evaluation", "bid_evaluation_completed", "contract_awarded"].includes(type)) return [];
  const selectedId = String(event?.data?.selected_contractor_id || event?.data?.contractor_id || project?.selectedContractorId || "");
  const bids = event?.data?.ranked_bids?.length ? event.data.ranked_bids : (event?.data?.bids?.length ? event.data.bids : bidRowsForProject(project));
  return bids.slice(0, 5).map((bid, index) => {
    const contractorId = bid.contractor_id || bid.contractorId;
    const price = bid.bid_price || bid.contract_sum;
    const isWinner = selectedId && String(contractorId) === selectedId;
    const score = Number(bid.evaluation_score || 0);
    return {
      id: `${contractorId || index}-${price || index}`,
      contractor: projectAgentNameById(contractorId, bid.contractor_name || `Bidder ${index + 1}`),
      price: formatProjectMoney(price),
      result: isWinner || bid.result === "Awarded" ? "Selected" : (score > 0 ? `Score ${Math.round(score * 100)}` : "Reviewed")
    };
  });
}

function eventTypeLabel(type) {
  const normalized = String(type || "event").toLowerCase();
  const labels = {
    agent_engaged: "Joined Project",
    agent_released: "Released from Project",
    agent_standby: "Moved to Standby",
    agent_recalled: "Recalled to Project",
    project_opportunity_initiated: "New Project Started",
    consultant_team_appointed: "Consultants Appointed",
    stage_transition: "Stage Changed",
    state_snapshot: "Simulation Update",
    construction_progress_updated: "Progress Updated",
    project_state_updated: "Performance Updated",
    tender_documents_prepared: "Tender Documents Ready",
    tender_opened: "Tender Opened",
    bid_submitted: "Bid Submitted",
    bid_declined: "Bid Declined",
    bid_evaluation_completed: "Preferred Bidder Selected",
    contract_awarded: "Contract Awarded",
    supplier_selected: "Supplier Appointed",
    project_completed: "Project Completed",
    enterprise_operation: "Enterprise Operation",
    out_of_project_operation: "Market Operation",
    status_active: "Active on Project",
    status_standby: "Standby Period",
    status_bidding: "Bidding Period",
    status_invited: "Invited to Tender",
    status_released: "Released Period"
  };
  return labels[normalized] || String(type || "event")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isEnterpriseActivityImportant(event) {
  return enterpriseImportantEventTypes.has(String(event?.event_type || "").toLowerCase());
}

function enterpriseActivityTitle(event) {
  const label = event?.data?.operation_label || event?.data?.operationLabel;
  return label ? String(label) : eventTypeLabel(event?.event_type);
}

function eventAtOrBeforePlayback(event) {
  const tick = Number(event?.tick);
  return !Number.isFinite(tick) || tick <= selectedEnterpriseHistoryTick.value;
}

function statusLabel(status) {
  return String(status || "free")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function projectStageLabel(stage) {
  const normalized = String(stage || "").toLowerCase();
  const labels = {
    initiation: "Initiation",
    design: "Design",
    feasibility: "Feasibility",
    consultant_selection: "Consultant Selection",
    concept_design: "Concept Design",
    detailed_design: "Detailed Design",
    statutory_approval: "Approval",
    approval: "Approval",
    tender_preparation: "Tender Preparation",
    tendering: "Tendering",
    bid_evaluation: "Bid Evaluation",
    contract_award: "Contract Award",
    mobilization: "Mobilization",
    construction: "Construction",
    completion: "Completion",
    handover: "Handover",
    final_account: "Final Account",
    closed: "Closed"
  };
  return labels[normalized] || statusLabel(stage);
}

function projectTypeLabel(type) {
  return String(type || "Construction")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function roleDisplayName(role) {
  const value = String(role || "enterprise").replace(/_/g, " ").trim();
  const normalized = value.toLowerCase();
  const aliases = {
    developer: "Owner",
    owner: "Owner",
    architect: "Architect",
    designer: "Architect",
    "design institute": "Architect",
    qs: "QS",
    "quantity surveyor": "QS",
    consultant: "Consultant",
    contractor: "Contractor",
    supplier: "Supplier",
    government: "Government"
  };
  return aliases[normalized] || value.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatEnterpriseDisplayName(name, fallback = "Enterprise") {
  const raw = String(name || "").trim();
  if (!raw) return fallback;
  const cleaned = raw
    .replace(/SyntheticConstructionAgent[_\s-]*(\d+)/gi, "Synthetic enterprise #$1")
    .replace(/SyntheticConstructionAgent/gi, "Synthetic enterprise")
    .replace(/SyntheticConstruction/gi, "Synthetic enterprise")
    .replace(/模拟咨询监理企业[_\s-]*(\d+)/g, "Simulated consultant #$1")
    .replace(/^(香港|澳门|深圳|广州|珠海|佛山|惠州|东莞|中山|江门|肇庆)\s*(Synthetic enterprise|Simulated consultant)/i, "$2")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || fallback;
}

function eventTimeLabel(tick) {
  const value = Number(tick);
  if (!Number.isFinite(value) || value <= 0) return "Simulation month";
  return `Month ${value}`;
}

function friendlyAgentName(agentId, fallback = "enterprise") {
  const id = String(agentId || "");
  if (!id) return fallback;
  if (selectedRuntimeEnterprise.value?.id === id) return selectedEnterpriseDisplayName.value;
  const enterprise = runtimeMapEnterprises.value.find((item) => item.nodeId === id);
  const name = enterprise?.node?.name || enterprise?.name;
  if (name) return formatEnterpriseDisplayName(name, fallback).slice(0, 30);
  return fallback;
}

function friendlyProjectName(projectId, fallback = "Project") {
  const id = String(projectId || "").trim();
  if (!id) return fallback;
  const project = runtimeMapProjects.value.find((item) => item.projectId === id);
  if (project?.name) return String(project.name).replace(/\s+/g, " ").trim();
  return id;
}

function enterpriseEventProjectId(event) {
  const data = event?.data || {};
  if (event?.project_id) return event.project_id;
  if (data.project_id) return data.project_id;
  if (data.projectId) return data.projectId;
  if (Array.isArray(data.project_ids) && data.project_ids.length) return data.project_ids[0];
  const match = String(event?.description || "").match(/\bP(?:GEN)?\d+\b/i);
  return match?.[0] || "";
}

function addEventDetail(rows, label, value) {
  const normalized = Array.isArray(value) ? value.filter(Boolean).join(", ") : value;
  if (normalized === undefined || normalized === null || normalized === "") return;
  rows.push({ label, value: String(normalized) });
}

function formatEventPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  return `${Math.round((numeric <= 1 ? numeric * 100 : numeric))}%`;
}

function enterpriseActivityDetailRows(event) {
  const data = event?.data || {};
  const rows = [];
  const projectId = enterpriseEventProjectId(event);
  const eventType = String(event?.event_type || "").toLowerCase();
  const status = data.status || (eventType.startsWith("status_") ? eventType.replace(/^status_/, "") : "");
  const agentId = data.agent_id || data.agentId || event?.agent_id;
  const contractorId = data.contractor_id || data.selected_contractor_id || data.selectedContractorId;
  const supplierId = data.supplier_id || data.selected_supplier_id || data.selectedSupplierId;
  const ownerId = data.owner_id || data.ownerId;
  const stage = data.stage || data.current_stage || data.next_stage;
  const amount = data.contract_sum || data.contractSum || data.bid_price || data.bidPrice || data.estimated_cost || data.initial_budget;
  addEventDetail(rows, "Operation", data.operation_label || data.operationLabel || "");
  addEventDetail(rows, "Project", projectId ? friendlyProjectName(projectId, projectId) : "");
  addEventDetail(rows, "Role", roleDisplayName(selectedRuntimeEnterprise.value?.role || selectedEnterpriseAgentProfile.value.role));
  addEventDetail(rows, "Status", status && !String(status).startsWith("status_") ? statusLabel(status) : "");
  addEventDetail(rows, "Stage", stage ? projectStageLabel(stage) : "");
  addEventDetail(rows, "Region", data.region || "");
  addEventDetail(rows, "Enterprise", friendlyAgentName(agentId, selectedEnterpriseDisplayName.value));
  addEventDetail(rows, "Owner", ownerId ? friendlyAgentName(ownerId, ownerId) : "");
  addEventDetail(rows, "Contractor", contractorId ? friendlyAgentName(contractorId, contractorId) : "");
  addEventDetail(rows, "Supplier", supplierId ? friendlyAgentName(supplierId, supplierId) : "");
  addEventDetail(rows, "Amount", amount ? formatProjectMoney(amount) : "");
  addEventDetail(rows, "Progress", data.progress !== undefined || data.actual_progress !== undefined ? formatEventPercent(data.progress ?? data.actual_progress) : "");
  addEventDetail(rows, "Quality", data.quality_score !== undefined || data.overall_quality !== undefined ? formatEventPercent(data.quality_score ?? data.overall_quality) : "");
  addEventDetail(rows, "Bid count", data.bid_count || data.valid_bids || data.bidders_count);
  addEventDetail(rows, "Result", data.result || data.review_result || data.approval_result);
  if (!rows.length) addEventDetail(rows, "Record", eventTypeLabel(event?.event_type));
  return rows.slice(0, 8);
}

function sanitizeEventDescription(description) {
  const cleaned = String(description || "")
    .replace(/\bGBA_[A-Z]+_\d+\b/g, "the enterprise")
    .replace(/\bPGEN\d+\b/g, "a generated project")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned ? `${cleaned.charAt(0).toUpperCase()}${cleaned.slice(1)}` : "";
}

function friendlyEventDescription(event) {
  const type = String(event?.event_type || "").toLowerCase();
  const description = String(event?.description || "");
  const role = description.match(/\b(Owner|Developer|Architect|Engineer|QS|Consultant|Contractor|Supplier|Government)\b/i)?.[1];
  const agentId = description.match(/\bGBA_[A-Z]+_\d+\b/)?.[0];
  const actor = friendlyAgentName(agentId, role ? `The ${roleDisplayName(role)}` : "This enterprise");
  const status = description.match(/engaged as ([a-z_]+)/i)?.[1];

  if (type === "agent_engaged") {
    return `${actor} joined as ${status ? statusLabel(status).toLowerCase() : "an active participant"}.`;
  }
  if (type === "agent_released") {
    if (/final account/i.test(description)) return "Final account was settled, so this enterprise was released from the project.";
    return `${actor} completed its current obligation and left the active project team.`;
  }
  if (type === "agent_standby") {
    return `${actor} moved to standby and can be recalled if the project needs support.`;
  }
  if (type === "agent_recalled") {
    return `${actor} was recalled to support an active project task.`;
  }
  if (type === "project_opportunity_initiated") {
    return `${actor} started a new project opportunity.`;
  }
  if (type === "tender_opened") {
    return "The project entered tendering and eligible contractors could submit bids.";
  }
  if (type === "bid_submitted") {
    return `${actor} submitted a bid for a project opportunity.`;
  }
  if (type === "bid_evaluation_completed") {
    return "The owner and QS compared submitted bids and selected the preferred contractor.";
  }
  if (type === "contract_awarded") {
    return "A contractor was awarded the contract and became responsible for delivery.";
  }
  if (type === "supplier_selected") {
    return "A supplier was appointed to support construction delivery.";
  }
  if (type === "construction_progress_updated") {
    const progress = event?.data?.progress ?? event?.data?.actual_progress;
    return `Construction progress was updated${progress !== undefined ? ` to ${formatEventPercent(progress)}` : ""}.`;
  }
  if (type === "enterprise_operation" || type === "out_of_project_operation") {
    return sanitizeEventDescription(event?.description) || "The enterprise performed a monthly business operation.";
  }
  if (type.startsWith("status_")) {
    const status = type.replace("status_", "");
    const projectId = enterpriseEventProjectId(event);
    return `${actor} was ${statusLabel(status).toLowerCase()}${projectId ? ` on ${friendlyProjectName(projectId, projectId)}` : ""}.`;
  }
  if (type === "stage_transition") {
    return sanitizeEventDescription(description).replace(/^Owner /i, "The owner ");
  }
  if (type === "state_snapshot") {
    return sanitizeEventDescription(description);
  }

  return sanitizeEventDescription(description) || "Simulation behavior was recorded for this item.";
}

function formatAnalyticsNumber(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return "0";
  return Math.round(numeric).toLocaleString();
}

function sparklinePoints(values = []) {
  const rows = values.map((value) => Number(value)).filter((value) => Number.isFinite(value));
  if (!rows.length) return "";
  const min = Math.min(...rows);
  const max = Math.max(...rows);
  const range = Math.max(1, max - min);
  return rows.map((value, index) => {
    const x = rows.length === 1 ? 48 : (index / (rows.length - 1)) * 92 + 2;
    const y = 30 - ((value - min) / range) * 24;
    return `${Number(x.toFixed(1))},${Number(y.toFixed(1))}`;
  }).join(" ");
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

async function runSimulation() {
  if (!procurementReady.value || running.value) return;
  if (procurementExecution.value.mode === "codedemo_micro" && integrationModelMode.value === "llm" && !integrationDataConsent.value) {
    workflowRunError.value = "Confirm the model data transfer or choose Offline fixture before running.";
    return;
  }
  running.value = true;
  workflowRunStatus.value = "running";
  workflowRunError.value = "";
  const databaseAgentCount = Number(simulationAgentCount.value) || 6000;
  const generatedProjectTarget = useDatabaseAgents.value
    ? Math.max(8, Math.min(80, Math.floor(databaseAgentCount / 160), Math.floor(Number(workflowTicks.value || 60) / 2)))
    : 4;
  const workflowPayload = buildWorkflowConfigurationPayload();
  const simulationPayload = {
    ...(procurementExecution.value.mode === "codedemo_micro" ? {
      integration_case_id: integrationCaseId.value,
      integration_model_mode: integrationModelMode.value,
      allow_model_data_transfer: integrationDataConsent.value
    } : {}),
    procurement_execution: { ...procurementExecution.value },
    ticks: workflowTicks.value,
    random_seed: 42,
    enable_project_generation: useDatabaseAgents.value,
    agent_source: useDatabaseAgents.value ? "database" : "default",
    agent_count: useDatabaseAgents.value ? databaseAgentCount : null,
    selected_cluster_id: workflowPayload.selected_cluster_id,
    agent_regions: workflowPayload.configuration.agent_regions,
    max_tender_invites: Number(maxTenderInvites.value),
    use_prior_network_edges: useDatabaseAgents.value && usePriorNetworkEdges.value,
    target_project_count: useDatabaseAgents.value ? generatedProjectTarget : null,
    max_active_projects: useDatabaseAgents.value ? Math.max(4, Math.min(28, Math.floor(generatedProjectTarget / 2) + 3)) : null,
    workflow_configuration: workflowPayload,
    phases: workflowPayload.phases,
    interventions: workflowPayload.interventions,
    events: workflowPayload.events,
    timeline_items: workflowTimelineItems.value
  };
  try {
    await checkBackend();
    const workflowId = workflowData.value?.workflow_id || "WF001";
    workflowData.value = await workflowApi.update(workflowId, workflowPayload);
    const created = await workflowApi.run(workflowId, simulationPayload);
    workflowRunResult.value = {
      ...created,
      agent_source: simulationPayload.agent_source,
      max_tender_invites: simulationPayload.max_tender_invites,
      use_prior_network_edges: simulationPayload.use_prior_network_edges,
      target_project_count: simulationPayload.target_project_count,
      max_active_projects: simulationPayload.max_active_projects
    };
    workflowRunStatus.value = "created";
    simulationId.value = created.simulation_id;
    defaultEnterpriseSelectionLocked.value = false;
    selectedRuntimeEnterprise.value = null;
    selectedEnterpriseHistory.value = null;
    resetRuntimeMapViewport();
    if (created.agent_count) simulationAgentCount.value = created.agent_count;
    activeView.value = "simulation";
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("view", "simulation");
    nextUrl.searchParams.set("simulation_id", created.simulation_id);
    window.history.replaceState({}, "", nextUrl);
    await nextTick();
    await loadSimulationOutputs();
    await nextTick();
    renderRuntimeMap();
  } catch (error) {
    console.warn("Workflow API run failed.", error);
    workflowRunStatus.value = "failed";
    workflowRunError.value = error.message || "Workflow simulation failed. Check the backend and workflow configuration.";
  } finally {
    running.value = false;
  }
}

async function loadSimulationOutputs() {
  if (!simulationId.value) return;
  try {
    stopPlayback();
    const [timeline, dashboard, metricResult] = await Promise.all([
      simulationApi.timeline(simulationId.value),
      analyticsApi.dashboard(simulationId.value),
      api.getMetrics(simulationId.value)
    ]);
    playbackTimeline.value = timeline?.ticks || [];
    const totalTrackedProjects = playbackTimeline.value.reduce(
      (maxCount, row) => Math.max(maxCount, Number(row.project_count || 0)),
      0
    );
    const initialProjectThreshold = totalTrackedProjects >= 12 ? 4 : Math.min(2, Math.max(1, totalTrackedProjects));
    const firstInterestingTick =
      playbackTimeline.value.find((row) => (
        Number(row.project_count || 0) >= initialProjectThreshold &&
        (Number(row.active_projects || 0) >= Math.min(4, initialProjectThreshold) ||
          Number(row.collaboration_edges || row.runtime_links || 0) >= initialProjectThreshold * 2)
      ))?.tick ||
      playbackTimeline.value.find((row) => Number(row.project_count || 0) >= initialProjectThreshold)?.tick ||
      playbackTimeline.value[0]?.tick ||
      1;
    const routeState = readRouteState();
    const requestedTick = routeState.simulationId === simulationId.value
      ? Number(routeState.tick || 0)
      : 0;
    const timelineMaxTick = playbackTimeline.value.reduce(
      (maxTick, row) => Math.max(maxTick, Number(row.tick || 0)),
      0
    );
    const targetTick = requestedTick > 0
      ? Math.max(1, Math.min(timelineMaxTick || requestedTick, requestedTick))
      : firstInterestingTick;
    // Loading or refreshing a run should only read generated history.
    // Generating new ticks belongs to explicit Play/Step/Seek actions.
    const readTick = timelineMaxTick > 0 ? Math.min(targetTick, timelineMaxTick) : undefined;
    const runtime = await simulationApi.runtimeState(simulationId.value, readTick);
    runtimeState.value = runtime;
    currentPlaybackTick.value = runtime.current_tick ?? firstInterestingTick;
    analyticsDashboard.value = dashboard;
    simulationResult.value = runtimeToLegacyResult(runtime);
    await maybeSelectDefaultRuntimeEnterprise(runtime);
    performanceHistory.value = playbackTimeline.value.length
      ? playbackTimeline.value.map((row) => ({
          tick: row.tick,
          actual_progress: row.average_progress,
          planned_progress: Math.min(1, row.tick / playbackMaxTick.value)
        }))
      : analyticsTrendToHistory(dashboard);
    networkData.value = analyticsNetworkToGraph(dashboard);
    metrics.value = metricResult;
  } catch (error) {
    console.warn("Runtime API loading failed; falling back to legacy simulation outputs.", error);
    const [performance, network, metricResult] = await Promise.all([
      api.getPerformance(simulationId.value, "P001"),
      api.getNetwork(simulationId.value),
      api.getMetrics(simulationId.value)
    ]);
    performanceHistory.value = performance.performance_history || [];
    playbackTimeline.value = performanceHistory.value.map((row) => ({
      tick: row.tick,
      date: row.date || `Tick ${row.tick}`,
      active_projects: 1,
      completed_projects: row.stage === "closed" ? 1 : 0,
      project_count: 1,
      average_progress: row.actual_progress || 0,
      average_quality: row.overall_quality || 0,
      delay_days: row.delay_days || 0,
      stage_counts: { [row.stage || "unknown"]: 1 },
      collaboration_edges: 0,
      resource_flows: 0,
      engaged_agents: 0,
      stage: row.stage || "",
      event_count: 0,
      important_events: []
    }));
    currentPlaybackTick.value = playbackTimeline.value[0]?.tick || 1;
    networkData.value = network;
    metrics.value = metricResult;
  }
  await nextTick();
  renderCharts();
}

function refreshCharts() {
  nextTick(renderCharts);
}

function renderCharts() {
  renderRadar(agentRadarRef.value, "agentRadar", ["Financial", "Technical", "Experience", "Innovation", "Compliance"], (selectedAgent.value?.capabilities || []).map((item) => Number(item.value.toFixed(1))));
  const clusterRadar = selectedClusterDetail.value?.capacity_radar;
  renderRadar(clusterRadarRef.value, "clusterRadar", ["Capacity", "Diversity", "Coordination", "Market Reach", "Growth"], clusterRadar ? [clusterRadar.capacity, clusterRadar.diversity, clusterRadar.coordination, clusterRadar.market_reach, clusterRadar.growth_potential] : [4.4, 4.0, 4.2, 4.1, 4.6]);
  const policyRadar = selectedPolicyDetail.value?.impact_radar;
  renderRadar(policyRadarRef.value, "policyRadar", ["Market Access", "Collaboration", "Compliance", "Cost", "Innovation"], policyRadar ? [policyRadar.market_access, policyRadar.collaboration, policyRadar.compliance, policyRadar.cost, policyRadar.innovation] : [4.2, 4.4, 3.8, 3.5, 4.0]);
  renderRuntimeMap();
  renderDonut();
  renderTrend();
  renderAnalyticsRegionMap();
  renderAnalyticsResourceFlow();
  renderNetwork();
}

function useChart(el, key) {
  if (!el) return null;
  let chart = chartCache.get(key);
  if (chart && !chart.isDisposed?.() && typeof chart.getDom === "function" && chart.getDom() !== el) {
    chart.dispose();
    chartCache.delete(key);
    chart = null;
  }
  if (!chart || chart.isDisposed?.()) {
    chart = echarts.init(el);
    chartCache.set(key, chart);
  }
  return chart;
}

function renderRadar(el, key, labels, values) {
  const chart = useChart(el, key);
  if (!chart) return;
  chart.setOption({
    color: ["#d98216"],
    radar: {
      radius: "68%",
      indicator: labels.map((name) => ({ name, max: 5 })),
      splitLine: { lineStyle: { color: "#eadfd4" } },
      axisLine: { lineStyle: { color: "#eadfd4" } },
      splitArea: { areaStyle: { color: ["#fffaf4", "#fff"] } }
    },
    series: [{ type: "radar", data: [{ value: values }], areaStyle: { color: "rgba(217,130,22,.18)" } }]
  });
}

function renderDonut() {
  const chart = useChart(clusterDonutRef.value, "clusterDonut");
  if (!chart) return;
  chart.setOption({
    color: ["#d98216", "#e8b36c", "#7f8b99", "#2f9d90", "#7b4ab0"],
    series: [{
      type: "pie",
      radius: ["48%", "72%"],
      label: { show: false },
      data: clusterComposition.value.map((item) => ({ value: item.value, name: item.label }))
    }]
  });
}

function renderTrend() {
  const chart = useChart(analyticsTrendRef.value, "analyticsTrend");
  if (!chart) return;
  const rawTrendRows = (performanceHistory.value || [])
    .map((row) => ({
      tick: Number(row.tick ?? row.month ?? 0),
      actual: Number(row.actual_progress ?? row.actual ?? 0),
      baseline: Number(row.planned_progress ?? row.baseline ?? 0)
    }))
    .filter((row) => Number.isFinite(row.tick) && row.tick >= 0)
    .sort((a, b) => a.tick - b.tick);
  const total = Math.max(
    24,
    Number(workflowTicks.value || 60),
    ...rawTrendRows.map((row) => Number(row.tick || 0))
  );
  const normalizeTrendValue = (value) => {
    const numeric = Number(value || 0);
    return numeric <= 1 ? numeric * 100 : numeric;
  };
  const interpolateRows = (tick, key, fallback) => {
    if (!rawTrendRows.length) return fallback;
    const rows = rawTrendRows.map((row) => ({
      tick: row.tick,
      value: normalizeTrendValue(row[key])
    }));
    if (tick <= rows[0].tick) {
      const anchor = rows[0].value;
      return Math.max(0, Math.min(anchor, anchor * (tick / Math.max(1, rows[0].tick))));
    }
    for (let index = 1; index < rows.length; index += 1) {
      const previous = rows[index - 1];
      const next = rows[index];
      if (tick <= next.tick) {
        const span = Math.max(1, next.tick - previous.tick);
        const ratio = (tick - previous.tick) / span;
        return previous.value + (next.value - previous.value) * ratio;
      }
    }
    const last = rows[rows.length - 1];
    const slopeBase = rows.length > 1 ? (last.value - rows[rows.length - 2].value) / Math.max(1, last.tick - rows[rows.length - 2].tick) : 0.25;
    return last.value + Math.max(0.05, slopeBase) * (tick - last.tick) * 0.35;
  };
  const interpolateFallbackTrend = (tick, anchors) => {
    const ratio = total ? tick / total : 0;
    const nextIndex = anchors.findIndex((anchor) => ratio <= anchor[0]);
    if (nextIndex <= 0) return anchors[0][1];
    const previous = anchors[nextIndex - 1];
    const next = anchors[nextIndex] || anchors[anchors.length - 1];
    const span = Math.max(0.001, next[0] - previous[0]);
    const localRatio = Math.max(0, Math.min(1, (ratio - previous[0]) / span));
    return previous[1] + (next[1] - previous[1]) * localRatio;
  };
  const history = Array.from({ length: total + 1 }, (_, tick) => {
    const fallbackProgress = interpolateFallbackTrend(tick, [
      [0, 12], [0.1, 18], [0.2, 30], [0.4, 55], [0.6, 66], [0.8, 75], [1, 84]
    ]) + Math.sin(tick / 2.9) * 1.1;
    const fallbackBaseline = interpolateFallbackTrend(tick, [
      [0, 10], [0.2, 22], [0.4, 34], [0.6, 38], [0.8, 44], [1, 50]
    ]) + Math.sin(tick / 5.4) * 0.6;
    const progress = interpolateRows(tick, "actual", fallbackProgress);
    const baseline = interpolateRows(tick, "baseline", fallbackBaseline);
    return {
      tick,
      label: `Month ${tick}`,
      actual: Math.max(0, Math.min(100, Number(progress.toFixed(1)))),
      baseline: Math.max(0, Math.min(100, Number(baseline.toFixed(1))))
    };
  });
  const phaseRows = workflowPeriodRows.value;
  const baselinePhase = phaseRows.find((item) => Number(item.startTick || 0) === 0) || phaseRows[0] || {
    title: "Baseline",
    startTick: 0,
    endTick: Math.min(24, total)
  };
  const continuationPhase = phaseRows.find((item) => Number(item.startTick || 0) > Number(baselinePhase.startTick || 0)) || {
    title: "Continue Simulation",
    startTick: Number(baselinePhase.endTick || 24),
    endTick: total
  };
  const defaultPolicyStart = Math.min(total - 1, Math.max(1, Math.round(total * 0.32)));
  const defaultPolicyEnd = Math.min(total, Math.max(defaultPolicyStart + 1, Math.round(total * 0.68)));
  const policyRowsForChart = (workflowPolicyRows.value.length ? workflowPolicyRows.value : [{
    title: "Cross-Regional Collaboration Policy",
    startTick: defaultPolicyStart,
    endTick: defaultPolicyEnd,
    type: "policy"
  }]).slice(0, 2).map((item) => {
    const start = Math.max(0, Math.min(total, Math.round(Number(item.startTick || 0))));
    const rawEnd = Math.round(Number(item.endTick ?? item.startTick ?? start));
    const end = Math.max(start + 1, Math.min(total, rawEnd > start ? rawEnd : start + Math.max(1, Math.round(total * 0.28))));
    return { ...item, startTick: start, endTick: end };
  });
  const eventRowsForChart = (workflowEventRows.value.length ? workflowEventRows.value : [{
    title: "Event",
    startTick: Math.min(total, Math.max(1, Math.round(total * 0.6))),
    type: "event"
  }]).slice(0, 2);
  const policyAreas = policyRowsForChart.map((item) => ([{
    name: `${item.title || "Policy"}\n${timelineMonthRangeLabel(item)}`,
    xAxis: `Month ${Math.round(Number(item.startTick || 0))}`,
    yAxis: 0
  }, {
    xAxis: `Month ${Math.round(Number(item.endTick || item.startTick || 0))}`,
    yAxis: 32
  }]));
  const policyEdgeMarkers = policyRowsForChart.flatMap((item) => [
    {
      xAxis: `Month ${Math.round(Number(item.startTick || 0))}`,
      label: { show: false },
      lineStyle: { color: "rgba(23, 107, 255, .42)", width: 1.25 }
    },
    {
      xAxis: `Month ${Math.round(Number(item.endTick || item.startTick || 0))}`,
      label: { show: false },
      lineStyle: { color: "rgba(23, 107, 255, .42)", width: 1.25 }
    }
  ]);
  const baselineEnd = Math.max(0, Math.min(total, Math.round(Number(baselinePhase.endTick || 0))));
  const continuationStart = Math.max(0, Math.min(total, Math.round(Number(continuationPhase.startTick || baselineEnd))));
  const continuationEnd = Math.max(continuationStart, Math.min(total, Math.round(Number(continuationPhase.endTick || total))));
  const continuationLabelTick = Math.round((continuationStart + continuationEnd) / 2);
  const periodMarkers = [
    {
      name: "Baseline",
      xAxis: `Month ${baselineEnd}`,
      label: { show: false },
      lineStyle: { color: "rgba(139, 92, 246, .42)", width: 1.35 }
    },
    {
      name: "Continue Simulation",
      xAxis: `Month ${continuationLabelTick}`,
      label: { show: false },
      lineStyle: { color: "rgba(255, 107, 34, .36)", width: 1.35 }
    }
  ];
  const eventMarkers = eventRowsForChart.map((item) => ({
    name: item.title || "Event",
    xAxis: `Month ${Math.round(Number(item.startTick || 0))}`,
    label: { show: false },
    lineStyle: { color: "rgba(10, 157, 98, .42)", width: 1.35 }
  }));
  const annotationPoints = [
    {
      name: `${baselinePhase.title || "Baseline"}\nMonth ${Math.round(Number(baselinePhase.startTick || 0))} - ${baselineEnd}`,
      coord: [`Month ${baselineEnd}`, 56],
      itemStyle: { color: "#8b5cf6" },
      label: { color: "#8b5cf6" }
    },
    ...policyRowsForChart.flatMap((item) => [
      {
        name: "",
        coord: [`Month ${Math.round(Number(item.startTick || 0))}`, 32],
        itemStyle: { color: "#176bff" },
        label: { show: false }
      },
      {
        name: "",
        coord: [`Month ${Math.round(Number(item.endTick || item.startTick || 0))}`, 32],
        itemStyle: { color: "#176bff" },
        label: { show: false }
      }
    ]),
    ...eventRowsForChart.map((item) => ({
      name: `Event\n${timelineMonthLabel(item.startTick)}`,
      coord: [`Month ${Math.round(Number(item.startTick || 0))}`, 66],
      itemStyle: { color: "#0a9d62" },
      label: { color: "#0a9d62" }
    })),
    {
      name: `${continuationPhase.title || "Continue Simulation"}\nMonth ${continuationStart} - ${continuationEnd}`,
      coord: [`Month ${continuationLabelTick}`, 70],
      itemStyle: { color: "#ff6b22" },
      label: { color: "#ff6b22" }
    }
  ];
  chart.setOption({
    grid: { left: 40, right: 18, top: 34, bottom: 32 },
    color: ["#ff6b22", "#94a3b8"],
    tooltip: { trigger: "axis" },
    legend: {
      show: false
    },
    xAxis: {
      type: "category",
      data: history.map((row) => row.label),
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#e4e7ec" } },
      axisTick: { show: false },
      axisLabel: {
        color: "#596579",
        fontWeight: 700,
        formatter: (value) => value.replace("Month ", "Month "),
        interval: (index) => index === 0 || index === history.length - 1 || Number(history[index]?.tick || 0) % 12 === 0
      }
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      axisLabel: { color: "#596579", fontWeight: 700 },
      splitLine: { lineStyle: { color: "rgba(16, 24, 40, .08)" } }
    },
    series: [
      {
        name: "Collaboration Index",
        type: "line",
        smooth: true,
        symbol: "none",
        lineStyle: { width: 3 },
        areaStyle: { color: "rgba(255, 107, 34, .07)" },
        data: history.map((row) => row.actual),
        markArea: {
          silent: true,
          itemStyle: {
            color: "rgba(23, 107, 255, .075)"
          },
          label: {
            show: true,
            position: "inside",
            color: "#176bff",
            fontSize: 11,
            fontWeight: 850,
            lineHeight: 15,
            formatter: ({ name }) => name
          },
          data: policyAreas
        },
        markLine: {
          symbol: "none",
          silent: true,
          label: { distance: 8, lineHeight: 15 },
          data: [...periodMarkers, ...eventMarkers, ...policyEdgeMarkers]
        },
        markPoint: {
          symbol: "circle",
          symbolSize: 6,
          silent: true,
          label: {
            show: true,
            position: "top",
            distance: 6,
            fontSize: 11,
            fontWeight: 850,
            lineHeight: 15,
            formatter: ({ name }) => name
          },
          data: annotationPoints
        }
      },
      {
        name: "No-policy Baseline",
        type: "line",
        smooth: true,
        symbol: "none",
        lineStyle: { width: 2, type: "dashed" },
        data: history.map((row) => row.baseline)
      }
    ]
  });
}

function renderAnalyticsRegionMap() {
  const chart = useChart(analyticsRegionMapRef.value, "analyticsRegionMap");
  if (!chart) return;
  const data = analyticsRegionMap.value.map((region) => ({
    name: region.name,
    value: region.value,
    region
  }));
  chart.off("click");
  chart.on("click", (params) => {
    if (params?.name) {
      selectedAnalyticsRegionName.value = params.name;
      nextTick(renderAnalyticsRegionMap);
    }
  });
  chart.setOption({
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const row = params.data?.region;
        if (!row) return `${params.name}<br/>No regional data`;
        return `<b>${row.label}</b><br/>Collaboration Index: ${row.value}<br/>Projects: ${row.projects}<br/>Cross-region Links: ${row.links}`;
      }
    },
    visualMap: {
      show: false,
      min: 30,
      max: 100,
      inRange: {
        color: ["#fff1b8", "#ffc66d", "#ff8b4a", "#f04438"]
      }
    },
    series: [{
      name: "Regional Collaboration Heat",
      type: "map",
      map: GBA_ANALYTICS_MAP_NAME,
      roam: false,
      selectedMode: false,
      layoutCenter: ["47%", "55%"],
      layoutSize: "112%",
      data,
      label: {
        show: true,
        color: "#273448",
        fontSize: 10,
        fontWeight: 850,
        formatter: (params) => {
          const row = params.data?.region;
          return row?.label || String(params.name || "").replace(" SAR", "");
        }
      },
      itemStyle: {
        borderColor: "rgba(255, 255, 255, .92)",
        borderWidth: 1.5,
        areaColor: "#ffe8a3",
        shadowColor: "rgba(16, 24, 40, .12)",
        shadowBlur: 8,
        shadowOffsetY: 4
      },
      emphasis: {
        label: {
          show: true,
          color: "#111827",
          fontWeight: 920
        },
        itemStyle: {
          areaColor: "#ff5b36",
          borderColor: "#fff",
          borderWidth: 2,
          shadowColor: "rgba(240, 68, 56, .24)",
          shadowBlur: 18
        }
      },
      select: {
        itemStyle: {
          areaColor: "#ff5b36"
        }
      }
    }]
  });
}

function renderAnalyticsResourceFlow() {
  const chart = useChart(analyticsResourceFlowRef.value, "analyticsResourceFlow");
  if (!chart) return;
  const { nodes, links } = analyticsResourceSankey.value;
  chart.setOption({
    tooltip: {
      trigger: "item",
      triggerOn: "mousemove",
      formatter: (params) => {
        if (params.dataType === "edge") {
          const source = String(params.data.source || "").replace(/^src-/, "");
          const target = String(params.data.target || "").replace(/^dst-/, "");
          return `<b>${source} -> ${target}</b><br/>Resource volume: ${params.data.value}`;
        }
        return `<b>${params.data.labelName || params.name}</b>`;
      }
    },
    series: [{
      type: "sankey",
      data: nodes,
      links,
      left: 8,
      right: 8,
      top: 6,
      bottom: 6,
      nodeWidth: 14,
      nodeGap: 12,
      nodeAlign: "justify",
      draggable: false,
      layoutIterations: 0,
      emphasis: { focus: "adjacency" },
      label: {
        show: true,
        color: "#273448",
        fontSize: 11,
        fontWeight: 850,
        formatter: (params) => params.data.labelName || params.name.replace(/^src-|^dst-/, "")
      },
      levels: [
        { depth: 0, label: { position: "right", distance: 9 } },
        { depth: 1, label: { position: "right", distance: 10 } }
      ],
      itemStyle: {
        borderRadius: 4
      },
      lineStyle: {
        color: "source",
        opacity: 0.28,
        curveness: 0.56
      }
    }]
  });
}

function renderNetwork() {
  const chart = useChart(analyticsNetworkRef.value, "analyticsNetwork");
  if (!chart) return;
  const nodes = (networkData.value.nodes || []).slice(0, 12).map((node) => ({
    id: node.id,
    name: node.id,
    symbolSize: node.node_type === "project" ? 52 : 36,
    category: node.node_type === "project" ? 1 : 0
  }));
  const links = (networkData.value.edges || []).map((edge) => ({ source: edge.source_agent_id, target: edge.target_agent_id }));
  const fallbackNodes = ["O001", "A001", "Q001", "C003", "S001", "P001"].map((name, index) => ({ id: name, name, symbolSize: index === 5 ? 52 : 36, category: index === 5 ? 1 : 0 }));
  const fallbackLinks = [
    { source: "O001", target: "A001" },
    { source: "O001", target: "Q001" },
    { source: "O001", target: "C003" },
    { source: "C003", target: "S001" },
    { source: "C003", target: "P001" }
  ];
  chart.setOption({
    color: ["#d98216", "#7b4ab0"],
    tooltip: {},
    series: [{
      type: "graph",
      layout: "force",
      roam: false,
      label: { show: true },
      force: { repulsion: 160, edgeLength: 110 },
      categories: [{ name: "Enterprise" }, { name: "Project" }],
      data: nodes.length ? nodes : fallbackNodes,
      links: links.length ? links : fallbackLinks,
      lineStyle: { color: "#9ba7b4", width: 1.4 }
    }]
  });
}

function buildRuntimeMapLines(linkType) {
  const limit = linkType === "resource_flow" ? 120 : 140;
  return runtimeLinks.value
    .filter((link) => link.link_type === linkType)
    .slice(0, limit)
    .map((link, index) => {
      const source = runtimeMapPointLookup.value.get(link.source_id) || linkCoordinate(link, "source");
      const target = runtimeMapPointLookup.value.get(link.target_id) || linkCoordinate(link, "target");
      return {
        name: `${link.source_id} -> ${link.target_id}`,
        coords: [source, target],
        value: Number((Number(link.strength || 0) * 100).toFixed(1)),
        link,
        lineStyle: {
          curveness: link.cross_city ? 0.26 + (index % 4) * 0.03 : 0.14
        }
      };
    });
}

function linkCoordinate(link, prefix) {
  const longitude = Number(link?.[`${prefix}_longitude`]);
  const latitude = Number(link?.[`${prefix}_latitude`]);
  if (Number.isFinite(longitude) && Number.isFinite(latitude)) return [longitude, latitude];
  return cityMetaFor("Shenzhen").center;
}

function renderRuntimeMap() {
  const chart = chartCache.get("runtimeMap");
  if (chart && !chart.isDisposed?.()) {
    chart.dispose();
  }
  chartCache.delete("runtimeMap");
}

function formatRuntimeMapTooltip(params) {
  if (params.seriesName === "Projects") {
    const data = params.data || {};
    return `<b>${data.name}</b><br/>${data.city || ""}<br/>Progress: ${data.progress || 0}%<br/>Type: ${data.projectType || "project"}`;
  }
  if (params.seriesName === "Enterprises") {
    const node = params.data?.node || {};
    return `<b>${node.name || params.name}</b><br/>${node.city || ""}<br/>Role: ${node.role || "enterprise"}<br/>Status: ${node.status || "active"}`;
  }
  if (params.seriesName === "Resource Flow" || params.seriesName === "Collaboration") {
    const link = params.data?.link || {};
    return `<b>${params.seriesName}</b><br/>Strength: ${Math.round((link.strength || 0) * 100)}%<br/>${link.cross_city ? "Cross-city" : "Same-city"}`;
  }
  if (!gbaRegionNameSet.has(params.name)) return `<b>${params.name || "World map"}</b><br/>World land background`;
  const city = cityMetaFor(params.name);
  return `<b>${city.name}</b><br/>${city.nameZh}<br/>Adcode: ${city.adcode}`;
}

function changeRuntimeMapZoom(delta) {
  const nextZoom = clampRuntimeMapZoom(runtimeMapZoom.value + delta);
  zoomRuntimeMapAtSvgPoint(nextZoom, { x: 500, y: 315 });
  nextTick(renderRuntimeMap);
}

function selectRuntimeRegion(regionName) {
  if (runtimeMapDragState.dragged) return;
  selectedRuntimeRegion.value = regionName;
}

function setHoveredRuntimeRegion(regionName) {
  hoveredRuntimeRegion.value = normalizeCityName(regionName);
}

function clearHoveredRuntimeRegion(regionName) {
  if (!regionName || hoveredRuntimeRegion.value === normalizeCityName(regionName)) {
    hoveredRuntimeRegion.value = "";
  }
}

function isRuntimeRegionHighlighted(regionName) {
  const normalized = normalizeCityName(regionName);
  return (
    (selectedRuntimeRegion.value && normalized === normalizeCityName(selectedRuntimeRegion.value)) ||
    (hoveredRuntimeRegion.value && normalized === hoveredRuntimeRegion.value)
  );
}

function clampRuntimeMapZoom(value) {
  return Math.max(0.72, Math.min(2.4, Number(value.toFixed(3))));
}

function clampRuntimeMapPan(pan, zoom = runtimeMapZoom.value) {
  const zoomOverflow = Math.max(0, zoom - 1);
  const maxX = 150 + zoomOverflow * 220;
  const maxY = 90 + zoomOverflow * 150;
  return {
    x: Math.max(-maxX, Math.min(maxX, Number(pan.x.toFixed(1)))),
    y: Math.max(-maxY, Math.min(maxY, Number(pan.y.toFixed(1))))
  };
}

function svgPointFromMapEvent(event) {
  const rect = event.currentTarget?.getBoundingClientRect?.();
  if (!rect?.width || !rect?.height) return { x: 500, y: 315 };
  return {
    x: ((event.clientX - rect.left) / rect.width) * 1000,
    y: ((event.clientY - rect.top) / rect.height) * 600
  };
}

function zoomRuntimeMapAtSvgPoint(nextZoom, anchor) {
  const currentZoom = Number(runtimeMapZoom.value || 1);
  const safeNextZoom = clampRuntimeMapZoom(nextZoom);
  if (Math.abs(safeNextZoom - currentZoom) < 0.001) return;
  const centerX = 500;
  const centerY = 315;
  const pan = runtimeMapPan.value || { x: 0, y: 0 };
  const sourceX = centerX + (anchor.x - pan.x - centerX) / currentZoom;
  const sourceY = centerY + (anchor.y - pan.y - centerY) / currentZoom;
  runtimeMapZoom.value = safeNextZoom;
  runtimeMapPan.value = clampRuntimeMapPan(
    {
      x: anchor.x - centerX - safeNextZoom * (sourceX - centerX),
      y: anchor.y - centerY - safeNextZoom * (sourceY - centerY)
    },
    safeNextZoom
  );
}

function handleRuntimeMapWheel(event) {
  if (event.target?.closest?.(".map-legend-box, .runtime-map-summary, .map-tool-buttons, .map-playback-inline")) return;
  const modeFactor = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 80 : 1;
  const normalizedDelta = event.deltaY * modeFactor;
  if (!Number.isFinite(normalizedDelta) || normalizedDelta === 0) return;
  event.preventDefault();
  const zoomFactor = Math.exp(-normalizedDelta * 0.0012);
  const anchor = svgPointFromMapEvent(event);
  zoomRuntimeMapAtSvgPoint(runtimeMapZoom.value * zoomFactor, anchor);
}

function startRuntimeMapDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  if (event.target?.closest?.(".map-legend-box, .runtime-map-summary, .map-tool-buttons, .map-playback-inline, .svg-project-pin, .svg-enterprise-marker, .svg-enterprise-dot, .svg-region-label")) return;
  runtimeMapDragState.active = true;
  runtimeMapDragState.dragged = false;
  runtimeMapDragState.pointerId = event.pointerId;
  runtimeMapDragState.startX = event.clientX;
  runtimeMapDragState.startY = event.clientY;
  runtimeMapDragState.originX = runtimeMapPan.value.x;
  runtimeMapDragState.originY = runtimeMapPan.value.y;
  runtimeMapDragging.value = true;
  event.currentTarget?.setPointerCapture?.(event.pointerId);
}

function moveRuntimeMapDrag(event) {
  if (!runtimeMapDragState.active) return;
  const dx = event.clientX - runtimeMapDragState.startX;
  const dy = event.clientY - runtimeMapDragState.startY;
  if (Math.abs(dx) + Math.abs(dy) > 4) runtimeMapDragState.dragged = true;
  runtimeMapPan.value = clampRuntimeMapPan({
    x: runtimeMapDragState.originX + dx,
    y: runtimeMapDragState.originY + dy
  });
}

function endRuntimeMapDrag(event) {
  if (!runtimeMapDragState.active) return;
  runtimeMapDragState.active = false;
  runtimeMapDragging.value = false;
  event?.currentTarget?.releasePointerCapture?.(runtimeMapDragState.pointerId);
  window.setTimeout(() => {
    runtimeMapDragState.dragged = false;
  }, 0);
}

function resetRuntimeMapViewport() {
  runtimeMapZoom.value = defaultRuntimeMapZoom;
  runtimeMapPan.value = defaultRuntimeMapPan();
  selectedRuntimeRegion.value = "";
  hoveredRuntimeRegion.value = "";
  const chart = chartCache.get("runtimeMap");
  if (chart && !chart.isDisposed?.()) chart.dispose();
  chartCache.delete("runtimeMap");
}

function resetRuntimeMap() {
  resetRuntimeMapViewport();
  nextTick(renderRuntimeMap);
}

watch(activeView, async () => {
  if (activeView.value !== "simulation") stopPlayback();
  syncRouteToUrl();
  if (activeView.value === "analytics" && simulationId.value && !runtimeState.value) {
    await loadSimulationOutputs();
  }
  nextTick(() => {
    renderCharts();
    resizeCharts();
  });
});
watch(analyticsActiveTab, async () => {
  if (activeView.value === "analytics") syncRouteToUrl({ replace: true });
  if (activeView.value !== "analytics" || analyticsActiveTab.value !== "overview") return;

  await nextTick();
  window.requestAnimationFrame(() => {
    if (activeView.value !== "analytics" || analyticsActiveTab.value !== "overview") return;
    renderTrend();
    renderAnalyticsRegionMap();
    renderAnalyticsResourceFlow();
    resizeCharts();
  });
});
watch(workflowInspectorOpen, () => {
  nextTick(updateTimelineShellHeight);
});
watch([agentTab, selectedAgentId], () => {
  nextTick(renderCharts);
});
watch(simulationId, () => {
  syncRouteToUrl({ replace: true });
});
watch(currentPlaybackTick, () => {
  if (activeView.value === "simulation" || activeView.value === "analytics") {
    syncRouteToUrl({ replace: true });
  }
});
watch(playbackSpeed, () => {
  if (simulationPlaying.value) startPlaybackTimer();
});
watch([agentKeyword, enterpriseTypeFilter, enterpriseRegionFilter], async () => {
  agentPage.value = 1;
  await loadAgentPage();
});
watch([policyKeyword, policyTypeFilter, policyRegionFilter], () => {
  if (policyRows.value.length && !policyRows.value.some((policy) => policy.name === selectedPolicy.value)) {
    selectedPolicy.value = policyRows.value[0].name;
  }
  if (policyMappingRows.value.length && !policyMappingRows.value.some((policy) => policy.id === selectedMappingPolicyId.value)) {
    selectMappingPolicy(policyMappingRows.value[0].id);
  }
  nextTick(renderCharts);
});
watch(selectedAgentId, async () => {
  await loadSelectedAgentProfile();
  agentDetailTab.value = "profile";
  chatMessages.value = [
    { sender: "user", text: "Could you introduce your core capabilities and project experience?" },
    { sender: "agent", text: `${selectedAgent.value.name} can explain its capabilities, policy response, and preferred collaboration modes through the backend chat endpoint.` }
  ];
});
watch(selectedCluster, async () => {
  await loadSelectedClusterDetail();
  nextTick(renderCharts);
});
watch(selectedPolicy, async () => {
  await loadSelectedPolicyDetail();
  nextTick(renderCharts);
});
watch(selectedMappingPolicyId, () => {
  const policy = activeMappingPolicy.value;
  if (policy?.scenarios?.length && !policy.scenarios.some((scenario) => scenario.id === selectedMappingScenarioId.value)) {
    selectedMappingScenarioId.value = policy.scenarios[0].id;
  }
  resetMechanismDraftForPolicy(policy);
});

onMounted(async () => {
  if (activeView.value === "policy") applyPolicyMappingStepFromUrl();
  syncRouteToUrl({ replace: true });
  window.addEventListener("popstate", applyRouteFromLocation);
  window.addEventListener("resize", resizeCharts);
  await checkBackend();
  await loadCatalogData();
  if (simulationId.value) {
    await loadSimulationOutputs();
  }
  renderCharts();
  window.addEventListener("resize", () => chartCache.forEach((chart) => chart.resize()));
});

onUnmounted(() => {
  stopPlayback();
  finishWorkflowTimelineDrag();
});
</script>
