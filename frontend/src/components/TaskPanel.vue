<template>
  <div class="task-panel">
    <div class="tp-header">
      <div class="tp-header-copy">
        <span class="tp-title">Tasks</span>
        <span class="tp-subtitle">Track agent-owned work during the simulation. Task updates and deliverables are published by the agents themselves.</span>
      </div>
      <div class="tp-header-actions">
        <span v-if="taskSummary.count || !loading" class="tp-count">{{ taskSummary.count }}</span>
        <button class="tp-ghost-btn" :disabled="loading" @click="loadTasks">
          {{ loading ? 'Refreshing...' : 'Refresh' }}
        </button>
      </div>
    </div>

    <div v-if="loading && tasks.length === 0" class="tp-state">
      Loading tasks...
    </div>

    <div v-else-if="error && tasks.length === 0" class="tp-state tp-error">
      <span>{{ error }}</span>
      <button class="tp-retry" @click="loadTasks">Retry</button>
    </div>

    <div v-else-if="!loading && tasks.length === 0" class="tp-state tp-empty">
      No tasks yet. Tasks will appear here when agents assign work during the simulation.
    </div>

    <div v-else class="tp-groups">
      <div class="tp-task-list">
        <article
          v-for="task in orderedTasks"
          :key="task.id"
          class="tp-task-card"
          :class="{ 'tp-task-card-expanded': isTaskExpanded(task) }"
        >
              <button
                class="tp-card-toggle"
                type="button"
                :aria-expanded="isTaskExpanded(task)"
                :aria-controls="`task-details-${task.id}`"
                @click="toggleTaskCard(task)"
              >
                <span class="tp-task-id">{{ task.issue_key || task.id }}</span>
                <span
                  v-if="isTaskExpanded(task)"
                  class="tp-status-pill"
                  :class="'tp-pill-' + task.status"
                >
                  <span class="tp-pill-dot"></span>
                  {{ statusLabel(task.status) }}
                </span>
                <span
                  v-else
                  class="tp-status-icon"
                  :class="'tp-pill-' + task.status"
                  :title="statusLabel(task.status)"
                  :aria-label="statusLabel(task.status)"
                ></span>
              </button>

              <div
                v-if="isTaskExpanded(task)"
                :id="`task-details-${task.id}`"
                class="tp-task-body"
              >
                <div class="tp-task-headline">
                  <h4 class="tp-task-title">{{ task.title || 'Untitled Task' }}</h4>
                  <p v-if="task.description" class="tp-task-description">{{ task.description }}</p>
                </div>

                <div class="tp-lifecycle" role="group" aria-label="Task lifecycle">
                  <div
                    v-for="step in lifecycleSteps(task)"
                    :key="`${task.id}-${step.key}`"
                    class="tp-lifecycle-step"
                    :class="`tp-step-${step.state}`"
                  >
                    <span class="tp-step-dot" aria-hidden="true"></span>
                    <span class="tp-step-label">{{ step.label }}</span>
                  </div>
                </div>

                <div class="tp-jira-grid">
                  <div class="tp-jira-field">
                    <span class="tp-detail-label">Issue</span>
                    <span>{{ task.issue_key || task.id }}</span>
                  </div>
                  <div class="tp-jira-field">
                    <span class="tp-detail-label">Reporter</span>
                    <span>{{ task.assigned_by || 'Unknown' }}</span>
                  </div>
                  <div class="tp-jira-field">
                    <span class="tp-detail-label">Assignee</span>
                    <span>{{ task.assigned_to || 'Unassigned' }}</span>
                  </div>
                  <div class="tp-jira-field">
                    <span class="tp-detail-label">Status</span>
                    <span>{{ statusLabel(task.status) }}</span>
                  </div>
                  <div class="tp-jira-field" v-if="task.deadline?.due_round !== null && task.deadline?.due_round !== undefined">
                    <span class="tp-detail-label">Due Round</span>
                    <span>R{{ task.deadline.due_round }}</span>
                  </div>
                  <div class="tp-jira-field" v-if="task.deadline?.remaining_rounds !== null && task.deadline?.remaining_rounds !== undefined">
                    <span class="tp-detail-label">Remaining</span>
                    <span>{{ formatRemainingRounds(task.deadline.remaining_rounds) }}</span>
                  </div>
                  <div class="tp-jira-field" v-if="task.deadline?.deadline_at">
                    <span class="tp-detail-label">Due Date</span>
                    <span>{{ formatDate(task.deadline.deadline_at) }}</span>
                  </div>
                  <div class="tp-jira-field" v-if="task.created_at">
                    <span class="tp-detail-label">Created</span>
                    <span>{{ formatDate(task.created_at) }}</span>
                  </div>
                  <div class="tp-jira-field" v-if="task.updated_at">
                    <span class="tp-detail-label">Updated</span>
                    <span>{{ formatDate(task.updated_at) }}</span>
                  </div>
                </div>

                <div
                  v-if="hasTaskDetails(task)"
                  class="tp-task-details"
                >
                  <div v-if="task.deliverable_metadata?.deliverable_type" class="tp-detail-line">
                    <span class="tp-detail-label">Deliverable</span>
                    <span>{{ formatDeliverableLabel(task.deliverable_metadata.deliverable_type) }}</span>
                  </div>

                  <div v-if="visibleAcceptanceCriteria(task).length" class="tp-detail-block">
                    <span class="tp-detail-label">Acceptance</span>
                    <ul class="tp-detail-list">
                      <li v-for="criterion in visibleAcceptanceCriteria(task)" :key="criterion">
                        {{ criterion }}
                      </li>
                    </ul>
                  </div>

                  <div v-if="visibleSuggestedTools(task).length" class="tp-detail-block">
                    <span class="tp-detail-label">Suggested tools</span>
                    <div class="tp-chip-row">
                      <span v-for="toolName in visibleSuggestedTools(task)" :key="toolName" class="tp-chip">
                        {{ toolName }}
                      </span>
                    </div>
                  </div>

                  <div v-if="task.deliverable_metadata?.tool_plan" class="tp-detail-line">
                    <span class="tp-detail-label">Tool plan</span>
                    <span>{{ task.deliverable_metadata.tool_plan }}</span>
                  </div>

                  <div v-if="task.latest_status_note" class="tp-detail-line">
                    <span class="tp-detail-label">Latest note</span>
                    <span>{{ task.latest_status_note }}</span>
                  </div>

                  <div v-if="latestChatSnippet(task)" class="tp-detail-line">
                    <span class="tp-detail-label">Public update</span>
                    <span>{{ latestChatSnippet(task) }}</span>
                  </div>
                </div>

                <div v-if="recentEvents(task).length" class="tp-task-events">
                  <span class="tp-detail-label">Recent Events</span>
                  <ul class="tp-event-list">
                    <li
                      v-for="event in recentEvents(task)"
                      :key="event.event_id"
                      class="tp-event-item"
                    >
                      <span class="tp-event-main">
                        <strong>{{ eventLabel(event.event_type) }}</strong>
                        <span v-if="event.actor"> by {{ event.actor }}</span>
                      </span>
                      <span class="tp-event-meta">{{ formatDate(event.created_at) }}</span>
                    </li>
                  </ul>
                </div>

                <div class="tp-task-actions">
                <span class="tp-readonly-badge">Agent-managed</span>
                <button
                  class="tp-action-btn"
                  @click="toggleArtifactPanel(task)"
                >
                  {{ isArtifactPanelOpen(task) ? 'Hide deliverables' : artifactButtonLabel(task) }}
                </button>
                </div>

                <div v-if="isArtifactPanelOpen(task)" class="tp-artifacts-panel">
                  <div class="tp-action-header">
                    <span class="tp-action-title">Deliverables</span>
                    <button class="tp-close-btn" @click="closeArtifactPanel">Done</button>
                  </div>

                  <div v-if="task.artifact_summaries?.length" class="tp-artifact-list">
                    <a
                      v-for="artifact in task.artifact_summaries"
                      :key="artifact.artifact_id"
                      class="tp-artifact-item"
                      :href="getArtifactDownloadHref(task, artifact)"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <span class="tp-artifact-name">{{ artifact.filename }}</span>
                      <span class="tp-artifact-meta">{{ formatArtifactSummary(artifact) }}</span>
                    </a>
                  </div>
                  <div v-else class="tp-artifact-empty">
                    No deliverables published yet.
                  </div>
                  <div class="tp-inline-message">
                    Deliverables appear here when the assignee publishes them from inside the simulation.
                  </div>
                </div>
              </div>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import {
  getSimulationTaskArtifactDownloadUrl,
  getSimulationTasks
} from '../api/simulation'

const props = defineProps({
  simulationId: {
    type: String,
    required: true
  },
  isSimulating: {
    type: Boolean,
    default: false
  }
})

const statusOrder = ['offered', 'open', 'in_progress', 'blocked', 'done', 'declined', 'expired']

const tasks = ref([])
const taskSummary = ref({ count: 0 })
const loading = ref(false)
const error = ref(null)
const expandedTaskId = ref('')
const artifactPanelTaskId = ref('')

let pollTimer = null
const statusRank = new Map(statusOrder.map((status, index) => [status, index]))
const genericAcceptanceDefaults = [
  'Produce a concrete deliverable using the current simulation context and available MCP tools.',
  'Do not rely on off-screen meetings or private conversations to finish the work.',
  'If the output is file-like, save it with save_task_artifact before completing the task.'
]
const genericSuggestedToolDefaults = ['update_task_status', 'save_task_artifact', 'complete_task']

const normalizeDetailToken = (value) => {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
}

const dedupeTextValues = (values) => {
  const unique = []
  const seen = new Set()

  for (const value of Array.isArray(values) ? values : []) {
    const text = String(value || '').trim()
    if (!text) {
      continue
    }
    const key = normalizeDetailToken(text)
    if (!key || seen.has(key)) {
      continue
    }
    seen.add(key)
    unique.push(text)
  }

  return unique
}

const visibleAcceptanceCriteria = (task) => {
  const deduped = dedupeTextValues(task?.deliverable_metadata?.acceptance_criteria)
  if (!deduped.length) {
    return []
  }

  const genericDefaults = new Set(genericAcceptanceDefaults.map(normalizeDetailToken))
  const specific = deduped.filter((criterion) => !genericDefaults.has(normalizeDetailToken(criterion)))
  return specific.length ? specific : []
}

const visibleSuggestedTools = (task) => {
  const deduped = dedupeTextValues(task?.deliverable_metadata?.suggested_tools)
  if (!deduped.length) {
    return []
  }

  const genericDefaults = new Set(genericSuggestedToolDefaults.map(normalizeDetailToken))
  const specific = deduped.filter((toolName) => !genericDefaults.has(normalizeDetailToken(toolName)))
  return specific.length ? specific : []
}

const hasTaskDetails = (task) => {
  return Boolean(
    task?.deliverable_metadata?.deliverable_type ||
    visibleAcceptanceCriteria(task).length ||
    visibleSuggestedTools(task).length ||
    task?.deliverable_metadata?.tool_plan ||
    task?.latest_status_note ||
    latestChatSnippet(task)
  )
}

const statusLabel = (status) => {
  const labels = {
    offered: 'Offered',
    open: 'Open',
    in_progress: 'In Progress',
    blocked: 'Blocked',
    done: 'Done',
    declined: 'Declined',
    expired: 'Expired'
  }
  return labels[status] || status
}

const formatDate = (value) => {
  if (!value) {
    return 'N/A'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return String(value)
  }
  return parsed.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const formatRemainingRounds = (value) => {
  const numeric = Number(value)
  if (Number.isNaN(numeric)) {
    return String(value)
  }
  if (numeric <= 0) {
    return 'Due now'
  }
  return `${numeric} round${numeric === 1 ? '' : 's'}`
}

const eventLabel = (eventType) => {
  const labels = {
    offered: 'Offered',
    accepted: 'Accepted',
    declined: 'Declined',
    started: 'Started',
    blocked: 'Blocked',
    completed: 'Completed',
    progress_updated: 'Progress Updated',
    reopened: 'Reopened',
    expired: 'Expired',
    artifact_saved: 'Deliverable Saved'
  }
  return labels[eventType] || formatDeliverableLabel(eventType)
}

const recentEvents = (task) => {
  const events = Array.isArray(task?.events) ? task.events : []
  return events.slice(-4).reverse()
}

const lifecycleSteps = (task) => {
  const status = task?.status || 'open'
  const steps = [
    { key: 'offer', label: 'Offered', state: 'pending' },
    { key: 'acceptance', label: 'Accepted', state: 'pending' },
    { key: 'execution', label: 'In Progress', state: 'pending' },
    { key: 'closure', label: 'Completed', state: 'pending' }
  ]

  if (status === 'offered') {
    steps[0].state = 'current'
    return steps
  }

  steps[0].state = 'done'

  if (status === 'declined') {
    steps[1].label = 'Declined'
    steps[1].state = 'current'
    steps[2].label = 'Not Started'
    steps[2].state = 'skipped'
    steps[3].label = 'Closed'
    steps[3].state = 'skipped'
    return steps
  }

  steps[1].state = 'done'

  if (status === 'open') {
    steps[1].state = 'current'
    return steps
  }

  if (status === 'in_progress') {
    steps[2].state = 'current'
    return steps
  }

  if (status === 'blocked') {
    steps[2].label = 'Blocked'
    steps[2].state = 'blocked'
    return steps
  }

  if (status === 'done') {
    steps[2].state = 'done'
    steps[3].state = 'current'
    return steps
  }

  if (status === 'expired') {
    steps[2].state = 'done'
    steps[3].label = 'Expired'
    steps[3].state = 'blocked'
    return steps
  }

  return steps
}

const taskSummaryText = (task) => {
  const title = String(task?.title || '').trim()
  const description = String(task?.description || '').trim()
  const deliverableType = String(task?.deliverable_metadata?.deliverable_type || '').trim()
  const deliverableLabel = deliverableType ? formatDeliverableLabel(deliverableType) : ''

  const normalizedTitle = title.toLowerCase()
  const normalizedDescription = description.toLowerCase()
  const instructionText = description && normalizedDescription !== normalizedTitle
    ? description
    : ''

  const summaryParts = []
  if (title) {
    summaryParts.push(title)
  } else if (instructionText) {
    summaryParts.push(instructionText)
  }

  if (instructionText) {
    const conciseInstruction = instructionText.length > 140
      ? `${instructionText.slice(0, 137).trimEnd()}...`
      : instructionText
    summaryParts.push(conciseInstruction)
  }

  if (deliverableLabel) {
    summaryParts.push(`Deliverable: ${deliverableLabel}`)
  }

  if (summaryParts.length > 0) {
    return summaryParts.join(' · ')
  }

  return 'No task description provided.'
}

const formatDeliverableLabel = (value) => {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase())
}

const latestChatSnippet = (task) => {
  const refs = Array.isArray(task?.chat_refs) ? task.chat_refs : []
  return refs.length ? String(refs[refs.length - 1]?.snippet || '') : ''
}

const isTaskExpanded = (task) => {
  return expandedTaskId.value === task.id
}

const closePanelsForTask = (taskId) => {
  if (artifactPanelTaskId.value === taskId) {
    closeArtifactPanel()
  }
}

const expandTaskCard = (taskId) => {
  if (expandedTaskId.value && expandedTaskId.value !== taskId) {
    closePanelsForTask(expandedTaskId.value)
  }
  expandedTaskId.value = taskId
}

const collapseTaskCard = (taskId) => {
  if (expandedTaskId.value !== taskId) {
    return
  }

  closePanelsForTask(taskId)
  expandedTaskId.value = ''
}

const toggleTaskCard = (task) => {
  if (isTaskExpanded(task)) {
    collapseTaskCard(task.id)
    return
  }

  expandTaskCard(task.id)
}

const orderedTasks = computed(() => {
  return tasks.value.slice().sort((left, right) => {
    const leftRank = statusRank.get(left.status || 'open') ?? statusOrder.length
    const rightRank = statusRank.get(right.status || 'open') ?? statusOrder.length

    if (leftRank !== rightRank) {
      return leftRank - rightRank
    }

    const leftTs = Date.parse(left.updated_at || left.created_at || 0)
    const rightTs = Date.parse(right.updated_at || right.created_at || 0)
    return rightTs - leftTs
  })
})

const taskRef = (task) => {
  return task.issue_key || task.id
}

const artifactButtonLabel = (task) => {
  const count = task?.artifact_count || 0
  return count > 0 ? `Deliverables (${count})` : 'Deliverables'
}

const formatBytes = (value) => {
  const numeric = Number(value || 0)
  if (!numeric) {
    return ''
  }
  if (numeric < 1024) {
    return `${numeric} B`
  }
  if (numeric < 1024 * 1024) {
    return `${(numeric / 1024).toFixed(1)} KB`
  }
  return `${(numeric / (1024 * 1024)).toFixed(1)} MB`
}

const formatArtifactSummary = (artifact) => {
  const parts = []
  if (artifact.media_type) {
    parts.push(artifact.media_type)
  }
  const sizeLabel = formatBytes(artifact.size_bytes)
  if (sizeLabel) {
    parts.push(sizeLabel)
  }
  return parts.join(' · ') || 'Download'
}

const getArtifactDownloadHref = (task, artifact) => {
  return artifact.download_url || getSimulationTaskArtifactDownloadUrl(props.simulationId, taskRef(task), artifact.artifact_id)
}

const applyTaskCollection = (payload) => {
  tasks.value = Array.isArray(payload?.tasks) ? payload.tasks : []
  taskSummary.value = {
    count: payload?.count || tasks.value.length
  }

  const validTaskIds = new Set(tasks.value.map((task) => task.id))
  if (expandedTaskId.value && !validTaskIds.has(expandedTaskId.value)) {
    expandedTaskId.value = ''
  }

  if (artifactPanelTaskId.value && !validTaskIds.has(artifactPanelTaskId.value)) {
    closeArtifactPanel()
  }
}

const loadTasks = async () => {
  if (!props.simulationId) {
    return
  }

  loading.value = true
  error.value = null
  try {
    const res = await getSimulationTasks(props.simulationId)
    applyTaskCollection(res.data)
  } catch (err) {
    error.value = err.message || 'Failed to load tasks'
  } finally {
    loading.value = false
  }
}

const isArtifactPanelOpen = (task) => {
  return artifactPanelTaskId.value === task.id
}

const closeArtifactPanel = () => {
  artifactPanelTaskId.value = ''
}

const toggleArtifactPanel = (task) => {
  if (isArtifactPanelOpen(task)) {
    closeArtifactPanel()
    return
  }
  expandTaskCard(task.id)
  artifactPanelTaskId.value = task.id
}

const refreshPanel = async () => {
  await loadTasks()
}

const startPolling = () => {
  if (pollTimer) {
    return
  }
  pollTimer = setInterval(() => {
    loadTasks()
  }, 10000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(
  () => props.simulationId,
  () => {
    refreshPanel()
  },
  { immediate: true }
)

watch(
  () => props.isSimulating,
  (isSimulating) => {
    if (isSimulating) {
      startPolling()
    } else {
      stopPolling()
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.task-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  font-family: 'Inter', system-ui, sans-serif;
  overflow: hidden;
}

.tp-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 24px 14px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.tp-header-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tp-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.tp-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  max-width: 560px;
}

.tp-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tp-count,
.tp-summary-value {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  padding: 2px 8px;
  border-radius: 10px;
  font-family: 'JetBrains Mono', monospace;
}

.tp-ghost-btn,
.tp-retry,
.tp-action-btn,
.tp-close-btn,
.tp-primary-btn {
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, color 0.2s, opacity 0.2s;
}

.tp-ghost-btn,
.tp-retry,
.tp-action-btn,
.tp-close-btn {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.tp-ghost-btn,
.tp-retry {
  padding: 7px 12px;
}

.tp-ghost-btn:hover,
.tp-retry:hover,
.tp-action-btn:hover,
.tp-close-btn:hover {
  background: var(--bg-tertiary);
  border-color: var(--border-hover);
}

.tp-ghost-btn:disabled,
.tp-retry:disabled,
.tp-action-btn:disabled,
.tp-primary-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.tp-primary-btn,
.tp-action-btn-primary {
  background: var(--accent-color);
  border: 1px solid var(--accent-color);
  color: #fff;
}

.tp-primary-btn {
  padding: 9px 14px;
}

.tp-primary-btn:hover,
.tp-action-btn-primary:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
}

.tp-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.tp-textarea {
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 10px 12px;
  font-size: 13px;
}

.tp-textarea:focus {
  border-color: var(--accent-color);
  outline: none;
  box-shadow: 0 0 0 2px rgba(74, 144, 226, 0.15);
}

.tp-textarea {
  resize: vertical;
  min-height: 92px;
  line-height: 1.5;
}

.tp-form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
}

.tp-form-footer-compact {
  margin-top: 12px;
}

.tp-inline-message {
  font-size: 12px;
  color: var(--text-secondary);
}

.tp-inline-error {
  color: var(--error-color);
}

.tp-inline-success {
  color: var(--success-color);
}

.tp-state {
  padding: 48px 24px;
  font-size: 13px;
  color: var(--text-secondary);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.tp-error {
  color: var(--error-color);
}

.tp-groups {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0 20px;
}

.tp-groups::-webkit-scrollbar {
  width: 4px;
}

.tp-groups::-webkit-scrollbar-thumb {
  background: var(--bg-tertiary);
  border-radius: 2px;
}

.tp-pill-dot {
  border-radius: 50%;
  flex-shrink: 0;
}

.tp-task-list {
  padding: 0 16px 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tp-task-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
}

.tp-task-card-expanded {
  border-color: var(--border-hover);
}

.tp-card-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.tp-card-toggle:hover {
  background: rgba(255, 255, 255, 0.02);
}

.tp-card-toggle:focus-visible {
  outline: 2px solid var(--accent-color);
  outline-offset: -2px;
}

.tp-task-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 14px 14px;
}

.tp-task-headline {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tp-task-title {
  margin: 0;
  font-size: 14px;
  line-height: 1.3;
  color: var(--text-primary);
}

.tp-task-description {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.45;
}

.tp-lifecycle {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.tp-lifecycle-step {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.02);
}

.tp-step-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--text-muted);
  flex-shrink: 0;
}

.tp-step-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.tp-step-done {
  border-color: rgba(76, 175, 80, 0.45);
  background: rgba(76, 175, 80, 0.1);
}

.tp-step-done .tp-step-dot,
.tp-step-current .tp-step-dot {
  background: var(--success-color, #4CAF50);
}

.tp-step-current {
  border-color: rgba(33, 150, 243, 0.45);
  background: rgba(33, 150, 243, 0.12);
}

.tp-step-current .tp-step-label {
  color: var(--text-primary);
}

.tp-step-blocked {
  border-color: rgba(244, 67, 54, 0.45);
  background: rgba(244, 67, 54, 0.12);
}

.tp-step-blocked .tp-step-dot {
  background: var(--error-color, #F44336);
}

.tp-step-skipped {
  opacity: 0.55;
}

.tp-jira-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.015);
}

.tp-jira-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.tp-task-actions,
.tp-action-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.tp-task-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.tp-status-icon {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  background: currentColor;
}

.tp-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 8px;
  border-radius: 10px;
  background: var(--bg-tertiary);
}

.tp-pill-dot {
  width: 5px;
  height: 5px;
}

.tp-pill-offered {
  color: var(--accent-color, #1A936F);
}

.tp-pill-offered .tp-pill-dot {
  background: var(--accent-color, #1A936F);
}

.tp-pill-open {
  color: var(--info-color, #2196F3);
}

.tp-pill-open .tp-pill-dot {
  background: var(--info-color, #2196F3);
}

.tp-pill-in_progress {
  color: var(--warning-color, #FF9800);
}

.tp-pill-in_progress .tp-pill-dot {
  background: var(--warning-color, #FF9800);
}

.tp-pill-blocked {
  color: var(--error-color, #F44336);
}

.tp-pill-blocked .tp-pill-dot {
  background: var(--error-color, #F44336);
}

.tp-pill-done {
  color: var(--success-color, #4CAF50);
}

.tp-pill-done .tp-pill-dot {
  background: var(--success-color, #4CAF50);
}

.tp-pill-declined {
  color: var(--text-muted);
}

.tp-pill-declined .tp-pill-dot {
  background: var(--text-muted);
}

.tp-pill-expired {
  color: #8B5CF6;
}

.tp-pill-expired .tp-pill-dot {
  background: #8B5CF6;
}

.tp-task-summary {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.tp-task-events {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tp-event-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tp-event-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
}

.tp-event-main {
  font-size: 12px;
  color: var(--text-secondary);
}

.tp-event-meta {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.tp-task-details {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
}

.tp-detail-line,
.tp-detail-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.tp-detail-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.tp-detail-list {
  margin: 0;
  padding-left: 16px;
}

.tp-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tp-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  font-size: 11px;
  color: var(--text-primary);
}

.tp-task-actions {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.tp-readonly-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(26, 147, 111, 0.12);
  border: 1px solid rgba(26, 147, 111, 0.24);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.tp-action-btn,
.tp-action-btn-primary {
  padding: 8px 10px;
}

.tp-action-composer {
  margin-top: 2px;
  padding: 12px;
  background: rgba(18, 18, 18, 0.4);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.tp-artifacts-panel {
  margin-top: 2px;
  padding: 12px;
  background: rgba(18, 18, 18, 0.28);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tp-artifact-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tp-artifact-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: inherit;
  text-decoration: none;
}

.tp-artifact-item:hover {
  border-color: var(--border-hover);
  background: var(--bg-tertiary);
}

.tp-artifact-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.tp-artifact-meta,
.tp-artifact-empty,
.tp-file-chip {
  font-size: 11px;
  color: var(--text-secondary);
}

.tp-artifact-upload {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tp-file-input {
  width: 100%;
  background: var(--bg-secondary);
  border: 1px dashed var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  padding: 10px 12px;
  font-size: 12px;
}

.tp-file-chip {
  display: inline-flex;
  width: fit-content;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 999px;
}

.tp-action-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.tp-close-btn {
  padding: 7px 10px;
}

@media (max-width: 960px) {
  .tp-header,
  .tp-form-footer,
  .tp-action-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .tp-header-actions {
    width: 100%;
    justify-content: space-between;
  }

  .tp-form-footer,
  .tp-form-footer-compact {
    align-items: stretch;
  }

  .tp-primary-btn,
  .tp-ghost-btn {
    width: 100%;
  }

  .tp-lifecycle {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .tp-jira-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
