<template>
  <div class="task-panel">
    <div class="tp-header">
      <div class="tp-header-copy">
        <span class="tp-title">Tasks</span>
        <span class="tp-subtitle">Create, assign, and advance work without leaving the simulation view.</span>
      </div>
      <div class="tp-header-actions">
        <span v-if="taskSummary.count || !loading" class="tp-count">{{ taskSummary.count }}</span>
        <button class="tp-ghost-btn" :disabled="loading" @click="loadTasks">
          {{ loading ? 'Refreshing...' : 'Refresh' }}
        </button>
      </div>
    </div>

    <div class="tp-toolbar">
      <div class="tp-field tp-field-actor">
        <label class="tp-label" for="task-actor-input">Acting as</label>
        <input
          id="task-actor-input"
          v-model="actingAs"
          class="tp-input"
          list="task-agent-options"
          placeholder="Choose or type an agent name"
          autocomplete="off"
        >
      </div>

      <div class="tp-field tp-field-filter">
        <label class="tp-label" for="task-status-filter">Status filter</label>
        <select id="task-status-filter" v-model="filters.status" class="tp-select">
          <option value="">All statuses</option>
          <option v-for="status in statusOrder" :key="status" :value="status">
            {{ statusLabel(status) }}
          </option>
        </select>
      </div>

      <div class="tp-field tp-field-filter">
        <label class="tp-label" for="task-assignee-filter">Assignee filter</label>
        <select id="task-assignee-filter" v-model="filters.assignedTo" class="tp-select">
          <option value="">All assignees</option>
          <option v-for="name in availableActors" :key="name" :value="name">{{ name }}</option>
        </select>
      </div>
    </div>

    <datalist id="task-agent-options">
      <option v-for="name in availableActors" :key="name" :value="name" />
    </datalist>

    <div class="tp-create-card">
      <div class="tp-card-header-row">
        <div>
          <div class="tp-card-title">Assign a task</div>
          <div class="tp-card-subtitle">The acting user is used as the assigner and lifecycle actor.</div>
        </div>
        <div class="tp-summary-pill">
          <span class="tp-summary-label">Visible keys</span>
          <span class="tp-summary-value">{{ taskSummary.count }}</span>
        </div>
      </div>

      <form class="tp-create-form" @submit.prevent="handleCreateTask">
        <div class="tp-form-grid">
          <div class="tp-field">
            <label class="tp-label" for="task-title-input">Title</label>
            <input
              id="task-title-input"
              v-model="createForm.title"
              class="tp-input"
              maxlength="160"
              placeholder="Investigate anomaly in supplier communication"
            >
          </div>

          <div class="tp-field">
            <label class="tp-label" for="task-assignee-input">Assign to</label>
            <input
              id="task-assignee-input"
              v-model="createForm.assignedTo"
              class="tp-input"
              list="task-agent-options"
              autocomplete="off"
              placeholder="Agent username"
            >
          </div>

          <div class="tp-field tp-field-span-2">
            <label class="tp-label" for="task-goal-input">Parent goal</label>
            <input
              id="task-goal-input"
              v-model="createForm.parentGoal"
              class="tp-input"
              maxlength="160"
              placeholder="Optional goal or investigation thread"
            >
          </div>

          <div class="tp-field tp-field-span-2">
            <label class="tp-label" for="task-description-input">Description</label>
            <textarea
              id="task-description-input"
              v-model="createForm.description"
              class="tp-textarea"
              rows="3"
              placeholder="Add context for the assignee."
            />
          </div>
        </div>

        <div class="tp-form-footer">
          <span v-if="formError" class="tp-inline-message tp-inline-error">{{ formError }}</span>
          <span v-else-if="feedbackMessage" class="tp-inline-message" :class="feedbackClass">{{ feedbackMessage }}</span>
          <button class="tp-primary-btn" type="submit" :disabled="createPending">
            {{ createPending ? 'Assigning...' : 'Assign task' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="loading && tasks.length === 0" class="tp-state">
      Loading tasks...
    </div>

    <div v-else-if="error && tasks.length === 0" class="tp-state tp-error">
      <span>{{ error }}</span>
      <button class="tp-retry" @click="loadTasks">Retry</button>
    </div>

    <div v-else-if="!loading && tasks.length === 0" class="tp-state tp-empty">
      No tasks yet. Create one manually or wait for the agents to assign work during the run.
    </div>

    <div v-else class="tp-groups">
      <template v-for="status in statusOrder" :key="status">
        <div v-if="tasksByStatus[status] && tasksByStatus[status].length > 0" class="tp-group">
          <button class="tp-group-header" @click="toggleGroup(status)">
            <div class="tp-group-left">
              <span class="tp-collapse">{{ collapsedGroups[status] ? '▶' : '▼' }}</span>
              <span class="tp-status-dot" :class="'tp-dot-' + status"></span>
              <span class="tp-group-label">{{ statusLabel(status) }}</span>
            </div>
            <span class="tp-group-count">{{ statusCount(status) }}</span>
          </button>

          <div v-show="!collapsedGroups[status]" class="tp-task-list">
            <article v-for="task in tasksByStatus[status]" :key="task.id" class="tp-task-card">
              <div class="tp-task-top">
                <div class="tp-task-keyline">
                  <span class="tp-task-id">{{ task.issue_key || task.id }}</span>
                  <span v-if="task.parent_goal" class="tp-goal-tag">{{ task.parent_goal }}</span>
                </div>
                <span class="tp-status-pill" :class="'tp-pill-' + task.status">
                  <span class="tp-pill-dot"></span>
                  {{ statusLabel(task.status) }}
                </span>
              </div>

              <div class="tp-task-title">{{ task.title }}</div>
              <div v-if="task.description" class="tp-task-description">{{ task.description }}</div>

              <div class="tp-task-assignment">
                <span class="tp-agent">{{ task.assigned_by || 'system' }}</span>
                <span class="tp-arrow">→</span>
                <span class="tp-agent">{{ task.assigned_to }}</span>
              </div>

              <div class="tp-task-meta">
                <span class="tp-meta-chip">Updated {{ formatTimestamp(task.updated_at) }}</span>
                <span class="tp-meta-chip">{{ task.events_count || 0 }} events</span>
              </div>

              <div v-if="task.latest_event" class="tp-latest-event">
                <span class="tp-event-label">Latest</span>
                <span class="tp-event-body">{{ formatLatestEvent(task.latest_event) }}</span>
              </div>

              <div v-if="task.output && task.status === 'done'" class="tp-output">
                {{ task.output }}
              </div>

              <div class="tp-task-actions">
                <button
                  v-if="canStart(task)"
                  class="tp-action-btn"
                  :disabled="isTaskMutating(task)"
                  @click="openActionComposer(task, 'start')"
                >
                  Start
                </button>
                <button
                  v-if="canBlock(task)"
                  class="tp-action-btn"
                  :disabled="isTaskMutating(task)"
                  @click="openActionComposer(task, 'block')"
                >
                  Block
                </button>
                <button
                  v-if="canComplete(task)"
                  class="tp-action-btn tp-action-btn-primary"
                  :disabled="isTaskMutating(task)"
                  @click="openActionComposer(task, 'complete')"
                >
                  Complete
                </button>
                <span v-if="actingAs && actingAs !== task.assigned_to" class="tp-action-hint">
                  Switch acting user to {{ task.assigned_to }} to update this task.
                </span>
              </div>

              <div v-if="isActionOpen(task)" class="tp-action-composer">
                <div class="tp-action-header">
                  <span class="tp-action-title">{{ actionTitle }}</span>
                  <button class="tp-close-btn" @click="closeActionComposer">Cancel</button>
                </div>

                <label class="tp-label" :for="`task-action-${task.id}`">{{ actionPrompt }}</label>
                <textarea
                  :id="`task-action-${task.id}`"
                  v-model="actionDraft.message"
                  class="tp-textarea"
                  rows="3"
                  :placeholder="actionPlaceholder"
                />

                <div class="tp-form-footer tp-form-footer-compact">
                  <span v-if="actionError" class="tp-inline-message tp-inline-error">{{ actionError }}</span>
                  <button
                    class="tp-primary-btn"
                    :disabled="actionPendingTaskId === task.id"
                    @click="submitTaskAction(task)"
                  >
                    {{ actionPendingTaskId === task.id ? actionButtonBusyLabel : actionButtonLabel }}
                  </button>
                </div>
              </div>
            </article>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import {
  blockSimulationTask,
  completeSimulationTask,
  createSimulationTask,
  getSimulationProfilesRealtime,
  getSimulationTasks,
  startSimulationTask
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

const statusOrder = ['open', 'in_progress', 'blocked', 'done']

const tasks = ref([])
const taskSummary = ref({ count: 0, filters: {}, status_counts: {} })
const loading = ref(false)
const error = ref(null)
const formError = ref('')
const actionError = ref('')
const createPending = ref(false)
const feedbackMessage = ref('')
const feedbackType = ref('success')
const profileActors = ref([])
const actingAs = ref('')
const collapsedGroups = ref({})
const actionDraft = ref({ taskId: '', mode: '', message: '' })
const actionPendingTaskId = ref('')
const filters = ref({
  status: '',
  assignedTo: ''
})
const createForm = ref({
  title: '',
  assignedTo: '',
  parentGoal: '',
  description: ''
})

let pollTimer = null

const statusLabel = (status) => {
  const labels = {
    open: 'Open',
    in_progress: 'In Progress',
    blocked: 'Blocked',
    done: 'Done'
  }
  return labels[status] || status
}

const uniqueNames = (values) => {
  const seen = new Set()
  return values.filter((value) => {
    const normalized = String(value || '').trim()
    if (!normalized) {
      return false
    }
    if (seen.has(normalized)) {
      return false
    }
    seen.add(normalized)
    return true
  })
}

const collectProfileNames = (profile) => {
  return uniqueNames([
    profile?.username,
    profile?.user_name,
    profile?.agent_name,
    profile?.name,
    profile?.realname,
    profile?.user_id
  ])
}

const availableActors = computed(() => {
  const taskActors = tasks.value.flatMap((task) => uniqueNames([
    task.assigned_to,
    task.assigned_by
  ]))
  return uniqueNames([
    ...profileActors.value,
    ...taskActors,
    actingAs.value,
    createForm.value.assignedTo
  ])
})

const feedbackClass = computed(() => {
  return feedbackType.value === 'error' ? 'tp-inline-error' : 'tp-inline-success'
})

const tasksByStatus = computed(() => {
  const groups = {}
  statusOrder.forEach((status) => {
    groups[status] = []
  })

  tasks.value.forEach((task) => {
    const status = task.status || 'open'
    if (!groups[status]) {
      groups[status] = []
    }
    groups[status].push(task)
  })

  Object.keys(groups).forEach((status) => {
    groups[status] = groups[status].slice().sort((left, right) => {
      const leftTs = Date.parse(left.updated_at || left.created_at || 0)
      const rightTs = Date.parse(right.updated_at || right.created_at || 0)
      return rightTs - leftTs
    })
  })

  return groups
})

const activeTask = computed(() => {
  return tasks.value.find((task) => task.id === actionDraft.value.taskId) || null
})

const actionTitle = computed(() => {
  if (actionDraft.value.mode === 'start') {
    return 'Start task'
  }
  if (actionDraft.value.mode === 'block') {
    return 'Block task'
  }
  if (actionDraft.value.mode === 'complete') {
    return 'Complete task'
  }
  return 'Update task'
})

const actionPrompt = computed(() => {
  if (actionDraft.value.mode === 'start') {
    return 'Optional note'
  }
  if (actionDraft.value.mode === 'block') {
    return 'Blocking reason'
  }
  if (actionDraft.value.mode === 'complete') {
    return 'Completion summary'
  }
  return 'Details'
})

const actionPlaceholder = computed(() => {
  if (actionDraft.value.mode === 'start') {
    return 'Optional context for the assignee starting the work.'
  }
  if (actionDraft.value.mode === 'block') {
    return 'Explain what is blocking progress.'
  }
  if (actionDraft.value.mode === 'complete') {
    return 'Summarize the delivered output.'
  }
  return 'Add details'
})

const actionButtonLabel = computed(() => {
  if (actionDraft.value.mode === 'start') {
    return 'Confirm start'
  }
  if (actionDraft.value.mode === 'block') {
    return 'Save blocked status'
  }
  if (actionDraft.value.mode === 'complete') {
    return 'Mark complete'
  }
  return 'Save'
})

const actionButtonBusyLabel = computed(() => {
  if (actionDraft.value.mode === 'start') {
    return 'Starting...'
  }
  if (actionDraft.value.mode === 'block') {
    return 'Blocking...'
  }
  if (actionDraft.value.mode === 'complete') {
    return 'Completing...'
  }
  return 'Saving...'
})

const statusCount = (status) => {
  return taskSummary.value.status_counts?.[status] ?? tasksByStatus.value[status]?.length ?? 0
}

const formatTimestamp = (value) => {
  if (!value) {
    return 'just now'
  }

  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }

  return parsed.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const formatLatestEvent = (event) => {
  if (!event) {
    return ''
  }

  const actor = event.actor || 'system'
  const eventType = event.event_type || 'updated'
  const note = event.details?.note || event.details?.output || ''
  return note ? `${actor} ${eventType}: ${note}` : `${actor} ${eventType}`
}

const resetFeedback = () => {
  feedbackMessage.value = ''
  feedbackType.value = 'success'
}

const setFeedback = (message, type = 'success') => {
  feedbackMessage.value = message
  feedbackType.value = type
}

const applyTaskCollection = (payload) => {
  tasks.value = Array.isArray(payload?.tasks) ? payload.tasks : []
  taskSummary.value = {
    count: payload?.count || tasks.value.length,
    filters: payload?.filters || {},
    status_counts: payload?.status_counts || {}
  }

  statusOrder.forEach((status) => {
    if (!(status in collapsedGroups.value)) {
      collapsedGroups.value[status] = false
    }
  })
}

const loadTasks = async () => {
  if (!props.simulationId) {
    return
  }

  loading.value = true
  error.value = null
  try {
    const res = await getSimulationTasks(props.simulationId, {
      status: filters.value.status || undefined,
      assigned_to: filters.value.assignedTo || undefined
    })
    applyTaskCollection(res.data)
  } catch (err) {
    error.value = err.message || 'Failed to load tasks'
  } finally {
    loading.value = false
  }
}

const loadAgentOptions = async () => {
  if (!props.simulationId) {
    return
  }

  const [redditProfiles, twitterProfiles] = await Promise.allSettled([
    getSimulationProfilesRealtime(props.simulationId, 'reddit'),
    getSimulationProfilesRealtime(props.simulationId, 'twitter')
  ])

  const names = []
  ;[redditProfiles, twitterProfiles].forEach((result) => {
    if (result.status === 'fulfilled') {
      const profiles = result.value?.data?.profiles || []
      profiles.forEach((profile) => {
        names.push(...collectProfileNames(profile))
      })
    }
  })

  profileActors.value = uniqueNames(names)
}

const syncDefaultActor = () => {
  if (!actingAs.value && availableActors.value.length > 0) {
    actingAs.value = availableActors.value[0]
  }
}

const handleCreateTask = async () => {
  formError.value = ''
  resetFeedback()

  const actor = String(actingAs.value || '').trim()
  const title = String(createForm.value.title || '').trim()
  const assignedTo = String(createForm.value.assignedTo || '').trim()

  if (!actor) {
    formError.value = 'Choose an acting user before creating a task.'
    return
  }
  if (!title) {
    formError.value = 'Task title is required.'
    return
  }
  if (!assignedTo) {
    formError.value = 'Assignee is required.'
    return
  }

  createPending.value = true
  try {
    await createSimulationTask(props.simulationId, {
      title,
      description: createForm.value.description,
      assigned_to: assignedTo,
      assigned_by: actor,
      parent_goal: createForm.value.parentGoal,
      actor
    })

    createForm.value = {
      title: '',
      assignedTo: '',
      parentGoal: '',
      description: ''
    }
    setFeedback('Task assigned successfully.')
    await loadTasks()
  } catch (err) {
    formError.value = err.message || 'Failed to create task'
  } finally {
    createPending.value = false
  }
}

const canStart = (task) => {
  return task.status === 'open' || task.status === 'blocked'
}

const canBlock = (task) => {
  return task.status === 'open' || task.status === 'in_progress'
}

const canComplete = (task) => {
  return task.status !== 'done'
}

const isActionOpen = (task) => {
  return actionDraft.value.taskId === task.id
}

const isTaskMutating = (task) => {
  return actionPendingTaskId.value === task.id
}

const openActionComposer = (task, mode) => {
  actionError.value = ''
  if (!actingAs.value) {
    actingAs.value = task.assigned_to || ''
  }
  actionDraft.value = {
    taskId: task.id,
    mode,
    message: ''
  }
}

const closeActionComposer = () => {
  actionError.value = ''
  actionDraft.value = { taskId: '', mode: '', message: '' }
}

const resolveActionActor = (task) => {
  const actor = String(actingAs.value || '').trim()
  if (actor) {
    return actor
  }
  return String(task.assigned_to || '').trim()
}

const submitTaskAction = async (task) => {
  actionError.value = ''
  resetFeedback()

  const actor = resolveActionActor(task)
  const message = String(actionDraft.value.message || '').trim()

  if (!actor) {
    actionError.value = 'Choose an acting user before updating a task.'
    return
  }
  if (actionDraft.value.mode === 'block' && !message) {
    actionError.value = 'Blocked tasks require a reason.'
    return
  }
  if (actionDraft.value.mode === 'complete' && !message) {
    actionError.value = 'Completed tasks require an output summary.'
    return
  }

  actionPendingTaskId.value = task.id
  try {
    if (actionDraft.value.mode === 'start') {
      await startSimulationTask(props.simulationId, task.id, {
        actor,
        reason: message
      })
      setFeedback(`Task ${task.issue_key || task.id} started.`)
    }

    if (actionDraft.value.mode === 'block') {
      await blockSimulationTask(props.simulationId, task.id, {
        actor,
        reason: message
      })
      setFeedback(`Task ${task.issue_key || task.id} blocked.`)
    }

    if (actionDraft.value.mode === 'complete') {
      await completeSimulationTask(props.simulationId, task.id, {
        actor,
        output: message
      })
      setFeedback(`Task ${task.issue_key || task.id} completed.`)
    }

    closeActionComposer()
    await loadTasks()
  } catch (err) {
    actionError.value = err.message || 'Failed to update task'
  } finally {
    actionPendingTaskId.value = ''
  }
}

const toggleGroup = (status) => {
  collapsedGroups.value[status] = !collapsedGroups.value[status]
}

const refreshPanel = async () => {
  resetFeedback()
  await Promise.all([loadTasks(), loadAgentOptions()])
  syncDefaultActor()
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
  () => [filters.value.status, filters.value.assignedTo],
  () => {
    loadTasks()
  }
)

watch(
  availableActors,
  () => {
    syncDefaultActor()
  }
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

.tp-toolbar,
.tp-create-card {
  flex-shrink: 0;
}

.tp-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1.8fr) repeat(2, minmax(160px, 1fr));
  gap: 12px;
  padding: 16px 24px 0;
}

.tp-create-card {
  margin: 16px 24px;
  padding: 16px;
  background: linear-gradient(180deg, rgba(74, 144, 226, 0.08), rgba(74, 144, 226, 0.02));
  border: 1px solid rgba(74, 144, 226, 0.25);
  border-radius: 10px;
}

.tp-card-header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.tp-card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.tp-card-subtitle {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.tp-summary-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: rgba(18, 18, 18, 0.35);
  border: 1px solid rgba(74, 144, 226, 0.2);
  border-radius: 999px;
}

.tp-summary-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}

.tp-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.tp-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tp-field-span-2 {
  grid-column: span 2;
}

.tp-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.tp-input,
.tp-select,
.tp-textarea {
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 10px 12px;
  font-size: 13px;
}

.tp-input:focus,
.tp-select:focus,
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
  padding: 8px 0 20px;
}

.tp-groups::-webkit-scrollbar {
  width: 4px;
}

.tp-groups::-webkit-scrollbar-thumb {
  background: var(--bg-tertiary);
  border-radius: 2px;
}

.tp-group {
  margin-bottom: 10px;
}

.tp-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  background: transparent;
  border: none;
  padding: 8px 24px;
  cursor: pointer;
  transition: background 0.15s;
}

.tp-group-header:hover {
  background: var(--bg-secondary);
}

.tp-group-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tp-collapse {
  font-size: 8px;
  color: var(--text-muted);
  width: 10px;
}

.tp-status-dot,
.tp-pill-dot {
  border-radius: 50%;
  flex-shrink: 0;
}

.tp-status-dot {
  width: 8px;
  height: 8px;
}

.tp-dot-open {
  background: var(--info-color, #2196F3);
}

.tp-dot-in_progress {
  background: var(--warning-color, #FF9800);
}

.tp-dot-blocked {
  background: var(--error-color, #F44336);
}

.tp-dot-done {
  background: var(--success-color, #4CAF50);
}

.tp-group-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.tp-group-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
  background: var(--bg-secondary);
  padding: 2px 8px;
  border-radius: 10px;
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
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tp-task-top,
.tp-task-keyline,
.tp-task-meta,
.tp-task-actions,
.tp-action-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.tp-task-keyline {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.tp-task-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-muted);
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

.tp-task-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.4;
}

.tp-task-description,
.tp-output,
.tp-latest-event {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.tp-task-assignment {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.tp-agent {
  color: var(--text-secondary);
}

.tp-arrow {
  color: var(--text-muted);
  font-size: 11px;
}

.tp-goal-tag,
.tp-meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  padding: 4px 8px;
}

.tp-task-meta {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.tp-latest-event {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.tp-event-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.tp-event-body {
  flex: 1;
}

.tp-output {
  background: rgba(18, 18, 18, 0.45);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
}

.tp-task-actions {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.tp-action-btn,
.tp-action-btn-primary {
  padding: 8px 10px;
}

.tp-action-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.tp-action-composer {
  margin-top: 2px;
  padding: 12px;
  background: rgba(18, 18, 18, 0.4);
  border: 1px solid var(--border-color);
  border-radius: 8px;
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
  .tp-card-header-row,
  .tp-form-footer,
  .tp-task-top,
  .tp-action-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .tp-toolbar,
  .tp-form-grid {
    grid-template-columns: 1fr;
  }

  .tp-field-span-2 {
    grid-column: span 1;
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
}
</style>
