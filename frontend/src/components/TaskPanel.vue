<template>
  <div class="task-panel">
    <div class="tp-header">
      <div class="tp-header-copy">
        <span class="tp-title">Tasks</span>
        <span class="tp-subtitle">Track agent work during the simulation.</span>
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
                <div class="tp-task-summary">{{ taskSummaryText(task) }}</div>

                <div
                  v-if="task.deliverable_metadata?.deliverable_type || task.deliverable_metadata?.acceptance_criteria?.length || task.deliverable_metadata?.suggested_tools?.length || task.deliverable_metadata?.tool_plan || task.latest_status_note || latestChatSnippet(task)"
                  class="tp-task-details"
                >
                  <div v-if="task.deliverable_metadata?.deliverable_type" class="tp-detail-line">
                    <span class="tp-detail-label">Deliverable</span>
                    <span>{{ formatDeliverableLabel(task.deliverable_metadata.deliverable_type) }}</span>
                  </div>

                  <div v-if="task.deliverable_metadata?.acceptance_criteria?.length" class="tp-detail-block">
                    <span class="tp-detail-label">Acceptance</span>
                    <ul class="tp-detail-list">
                      <li v-for="criterion in task.deliverable_metadata.acceptance_criteria" :key="criterion">
                        {{ criterion }}
                      </li>
                    </ul>
                  </div>

                  <div v-if="task.deliverable_metadata?.suggested_tools?.length" class="tp-detail-block">
                    <span class="tp-detail-label">Suggested tools</span>
                    <div class="tp-chip-row">
                      <span v-for="toolName in task.deliverable_metadata.suggested_tools" :key="toolName" class="tp-chip">
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

                <div class="tp-task-actions">
                <button
                  v-if="canAccept(task)"
                  class="tp-action-btn tp-action-btn-primary"
                  :disabled="isTaskMutating(task)"
                  @click="openActionComposer(task, 'accept')"
                >
                  Accept
                </button>
                <button
                  v-if="canDecline(task)"
                  class="tp-action-btn"
                  :disabled="isTaskMutating(task)"
                  @click="openActionComposer(task, 'decline')"
                >
                  Decline
                </button>
                <button
                  v-if="canStart(task)"
                  class="tp-action-btn"
                  :disabled="isTaskMutating(task)"
                  @click="openActionComposer(task, 'start')"
                >
                  Start
                </button>
                <button
                  v-if="canUpdate(task)"
                  class="tp-action-btn"
                  :disabled="isTaskMutating(task)"
                  @click="openActionComposer(task, 'update')"
                >
                  Update
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
                <button
                  class="tp-action-btn"
                  :disabled="artifactPendingTaskId === task.id"
                  @click="toggleArtifactPanel(task)"
                >
                  {{ isArtifactPanelOpen(task) ? 'Hide deliverables' : artifactButtonLabel(task) }}
                </button>
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
                    <span
                      v-else-if="actionDraft.mode === 'complete' && !requiresCompletionSummary(task)"
                      class="tp-inline-message"
                    >
                      Optional because this task already has a staged deliverable.
                    </span>
                    <button
                      class="tp-primary-btn"
                      :disabled="actionPendingTaskId === task.id"
                      @click="submitTaskAction(task)"
                    >
                      {{ actionPendingTaskId === task.id ? actionButtonBusyLabel : actionButtonLabel }}
                    </button>
                  </div>
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
                    No deliverables uploaded yet.
                  </div>

                  <div v-if="canUploadDeliverable(task)" class="tp-artifact-upload">
                    <label class="tp-label" :for="`task-artifact-${task.id}`">Upload a deliverable</label>
                    <input
                      :id="`task-artifact-${task.id}`"
                      :key="artifactInputKey"
                      class="tp-file-input"
                      type="file"
                      accept=".md,.markdown,.txt,.pdf"
                      @change="handleArtifactFileSelected(task, $event)"
                    >

                    <div v-if="artifactDraft.fileName" class="tp-file-chip">
                      Selected {{ artifactDraft.fileName }}
                    </div>

                    <label class="tp-label" :for="`task-artifact-note-${task.id}`">Optional note</label>
                    <textarea
                      :id="`task-artifact-note-${task.id}`"
                      v-model="artifactDraft.note"
                      class="tp-textarea"
                      rows="2"
                      placeholder="Describe what this deliverable contains."
                    />

                    <div class="tp-form-footer tp-form-footer-compact">
                      <span v-if="artifactError" class="tp-inline-message tp-inline-error">{{ artifactError }}</span>
                      <span v-else class="tp-inline-message">Allowed formats: .md, .txt, .pdf</span>
                      <button
                        class="tp-primary-btn"
                        :disabled="artifactPendingTaskId === task.id"
                        @click="submitArtifact(task)"
                      >
                        {{ artifactPendingTaskId === task.id ? 'Uploading...' : 'Upload deliverable' }}
                      </button>
                    </div>
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
  acceptSimulationTask,
  blockSimulationTask,
  completeSimulationTask,
  declineSimulationTask,
  getSimulationTaskArtifactDownloadUrl,
  getSimulationTasks,
  saveSimulationTaskArtifact,
  startSimulationTask,
  updateSimulationTaskStatus
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
const artifactAcceptExtensions = ['md', 'markdown', 'txt', 'pdf']

const tasks = ref([])
const taskSummary = ref({ count: 0 })
const loading = ref(false)
const error = ref(null)
const actionError = ref('')
const expandedTaskId = ref('')
const actionDraft = ref({ taskId: '', mode: '', message: '' })
const actionPendingTaskId = ref('')
const artifactDraft = ref({ taskId: '', note: '', file: null, fileName: '' })
const artifactPendingTaskId = ref('')
const artifactError = ref('')
const artifactInputKey = ref(0)

let pollTimer = null
const statusRank = new Map(statusOrder.map((status, index) => [status, index]))

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

const taskSummaryText = (task) => {
  const title = String(task?.title || '').trim()
  const description = String(task?.description || '').trim()

  if (title && description && title.toLowerCase() !== description.toLowerCase()) {
    return `${title}: ${description}`
  }

  return title || description || 'No task description provided.'
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
  if (actionDraft.value.taskId === taskId) {
    closeActionComposer()
  }
  if (artifactDraft.value.taskId === taskId) {
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

const actionTitle = computed(() => {
  if (actionDraft.value.mode === 'accept') {
    return 'Accept task offer'
  }
  if (actionDraft.value.mode === 'decline') {
    return 'Decline task offer'
  }
  if (actionDraft.value.mode === 'start') {
    return 'Start task'
  }
  if (actionDraft.value.mode === 'update') {
    return 'Post progress update'
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
  if (actionDraft.value.mode === 'accept') {
    return 'Optional acceptance note'
  }
  if (actionDraft.value.mode === 'decline') {
    return 'Decline reason'
  }
  if (actionDraft.value.mode === 'start') {
    return 'Optional note'
  }
  if (actionDraft.value.mode === 'update') {
    return 'Progress note'
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
  if (actionDraft.value.mode === 'accept') {
    return 'Optional plan for how you will handle this work.'
  }
  if (actionDraft.value.mode === 'decline') {
    return 'Explain why you cannot take this on.'
  }
  if (actionDraft.value.mode === 'start') {
    return 'Optional context for the assignee starting the work.'
  }
  if (actionDraft.value.mode === 'update') {
    return 'Share a concise progress update or status note.'
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
  if (actionDraft.value.mode === 'accept') {
    return 'Accept offer'
  }
  if (actionDraft.value.mode === 'decline') {
    return 'Decline offer'
  }
  if (actionDraft.value.mode === 'start') {
    return 'Confirm start'
  }
  if (actionDraft.value.mode === 'update') {
    return 'Save update'
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
  if (actionDraft.value.mode === 'accept') {
    return 'Accepting...'
  }
  if (actionDraft.value.mode === 'decline') {
    return 'Declining...'
  }
  if (actionDraft.value.mode === 'start') {
    return 'Starting...'
  }
  if (actionDraft.value.mode === 'update') {
    return 'Saving update...'
  }
  if (actionDraft.value.mode === 'block') {
    return 'Blocking...'
  }
  if (actionDraft.value.mode === 'complete') {
    return 'Completing...'
  }
  return 'Saving...'
})

const requiresCompletionSummary = (task) => {
  return !((task?.artifact_count || 0) > 0)
}

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

  if (actionDraft.value.taskId && !validTaskIds.has(actionDraft.value.taskId)) {
    closeActionComposer()
  }
  if (artifactDraft.value.taskId && !validTaskIds.has(artifactDraft.value.taskId)) {
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

const hasAssignee = (task) => {
  return Boolean(String(task?.assigned_to || '').trim())
}

const canStart = (task) => {
  return hasAssignee(task) && (task.status === 'open' || task.status === 'blocked')
}

const canAccept = (task) => {
  return hasAssignee(task) && task.status === 'offered'
}

const canDecline = (task) => {
  return hasAssignee(task) && task.status === 'offered'
}

const canBlock = (task) => {
  return hasAssignee(task) && (task.status === 'open' || task.status === 'in_progress')
}

const canUpdate = (task) => {
  return hasAssignee(task) && ['open', 'in_progress', 'blocked'].includes(task.status)
}

const canComplete = (task) => {
  return hasAssignee(task) && ['open', 'in_progress', 'blocked'].includes(task.status)
}

const canUploadDeliverable = (task) => {
  return hasAssignee(task) && !['declined', 'expired'].includes(task.status)
}

const isActionOpen = (task) => {
  return actionDraft.value.taskId === task.id
}

const isArtifactPanelOpen = (task) => {
  return artifactDraft.value.taskId === task.id
}

const isTaskMutating = (task) => {
  return actionPendingTaskId.value === task.id
}

const openActionComposer = (task, mode) => {
  actionError.value = ''
  expandTaskCard(task.id)
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

const closeArtifactPanel = () => {
  artifactError.value = ''
  artifactDraft.value = { taskId: '', note: '', file: null, fileName: '' }
  artifactInputKey.value += 1
}

const toggleArtifactPanel = (task) => {
  artifactError.value = ''
  if (isArtifactPanelOpen(task)) {
    closeArtifactPanel()
    return
  }
  expandTaskCard(task.id)
  artifactDraft.value = {
    taskId: task.id,
    note: '',
    file: null,
    fileName: ''
  }
  artifactInputKey.value += 1
}

const resolveActionActor = (task) => {
  return String(task.assigned_to || '').trim()
}

const inferMediaType = (filename) => {
  const normalized = String(filename || '').trim().toLowerCase()
  if (normalized.endsWith('.pdf')) {
    return 'application/pdf'
  }
  if (normalized.endsWith('.md') || normalized.endsWith('.markdown')) {
    return 'text/markdown'
  }
  return 'text/plain'
}

const isAllowedArtifactFile = (file) => {
  const fileName = String(file?.name || '').toLowerCase()
  const extension = fileName.includes('.') ? fileName.split('.').pop() : ''
  return artifactAcceptExtensions.includes(extension)
}

const readFileAsBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result)
      let binary = ''
      bytes.forEach((value) => {
        binary += String.fromCharCode(value)
      })
      resolve(window.btoa(binary))
    }
    reader.onerror = () => {
      reject(new Error('Failed to read the selected file.'))
    }
    reader.readAsArrayBuffer(file)
  })
}

const handleArtifactFileSelected = (task, event) => {
  artifactError.value = ''
  const file = event?.target?.files?.[0]
  if (!file) {
    artifactDraft.value = { ...artifactDraft.value, taskId: task.id, file: null, fileName: '' }
    return
  }
  if (!isAllowedArtifactFile(file)) {
    artifactError.value = 'Unsupported file type. Use .md, .txt, or .pdf.'
    artifactDraft.value = { ...artifactDraft.value, taskId: task.id, file: null, fileName: '' }
    artifactInputKey.value += 1
    return
  }
  artifactDraft.value = {
    ...artifactDraft.value,
    taskId: task.id,
    file,
    fileName: file.name
  }
}

const submitArtifact = async (task) => {
  artifactError.value = ''

  const actor = resolveActionActor(task)
  const file = artifactDraft.value.file

  if (!actor) {
    artifactError.value = 'This task has no assignee, so no deliverable can be uploaded from the panel.'
    return
  }
  if (!file) {
    artifactError.value = 'Choose a deliverable file first.'
    return
  }
  if (!isAllowedArtifactFile(file)) {
    artifactError.value = 'Unsupported file type. Use .md, .txt, or .pdf.'
    return
  }

  artifactPendingTaskId.value = task.id
  try {
    const content = await readFileAsBase64(file)
    await saveSimulationTaskArtifact(props.simulationId, taskRef(task), {
      actor,
      filename: file.name,
      content,
      encoding: 'base64',
      media_type: file.type || inferMediaType(file.name),
      kind: 'deliverable',
      note: String(artifactDraft.value.note || '').trim() || undefined
    })
    artifactDraft.value = {
      taskId: task.id,
      note: '',
      file: null,
      fileName: ''
    }
    artifactInputKey.value += 1
    await loadTasks()
  } catch (err) {
    artifactError.value = err.message || 'Failed to upload deliverable'
  } finally {
    artifactPendingTaskId.value = ''
  }
}

const submitTaskAction = async (task) => {
  actionError.value = ''

  const actor = resolveActionActor(task)
  const message = String(actionDraft.value.message || '').trim()

  if (!actor) {
    actionError.value = 'This task has no assignee, so it cannot be updated from the panel.'
    return
  }
  if (actionDraft.value.mode === 'decline' && !message) {
    actionError.value = 'Declined offers require a reason.'
    return
  }
  if (actionDraft.value.mode === 'block' && !message) {
    actionError.value = 'Blocked tasks require a reason.'
    return
  }
  if (actionDraft.value.mode === 'update' && !message) {
    actionError.value = 'Progress updates require a note.'
    return
  }
  if (actionDraft.value.mode === 'complete' && !message && requiresCompletionSummary(task)) {
    actionError.value = 'Completed tasks require an output summary or a staged deliverable.'
    return
  }

  actionPendingTaskId.value = task.id
  try {
    if (actionDraft.value.mode === 'accept') {
      await acceptSimulationTask(props.simulationId, taskRef(task), {
        actor,
        reason: message
      })
    }

    if (actionDraft.value.mode === 'decline') {
      await declineSimulationTask(props.simulationId, taskRef(task), {
        actor,
        reason: message
      })
    }

    if (actionDraft.value.mode === 'start') {
      await startSimulationTask(props.simulationId, taskRef(task), {
        actor,
        reason: message
      })
    }

    if (actionDraft.value.mode === 'update') {
      await updateSimulationTaskStatus(props.simulationId, taskRef(task), {
        actor,
        status: task.status,
        reason: message
      })
    }

    if (actionDraft.value.mode === 'block') {
      await blockSimulationTask(props.simulationId, taskRef(task), {
        actor,
        reason: message
      })
    }

    if (actionDraft.value.mode === 'complete') {
      await completeSimulationTask(props.simulationId, taskRef(task), {
        actor,
        output: message
      })
    }

    closeActionComposer()
    await loadTasks()
  } catch (err) {
    actionError.value = err.message || 'Failed to update task'
  } finally {
    actionPendingTaskId.value = ''
  }
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
}
</style>
