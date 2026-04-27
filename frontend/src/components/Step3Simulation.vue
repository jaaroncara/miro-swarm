<template>
  <div class="simulation-panel">
    <!-- Top Control Bar -->
    <div class="control-bar">
      <div class="status-group">
        <!-- Twitter Platform Progress -->
        <div class="platform-status twitter" :class="{ active: runStatus.twitter_running, completed: runStatus.twitter_completed }">
          <div class="platform-header">
            <svg class="platform-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
            </svg>
            <span class="platform-name">Company Channels (Slack)</span>
            <span v-if="runStatus.twitter_completed" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">ROUND</span>
              <span class="stat-value mono">{{ runStatus.twitter_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || maxRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">Elapsed Time</span>
              <span class="stat-value mono">{{ twitterElapsedTime }}</span>
            </span>
            <span class="stat">
              <span class="stat-label">ACTS</span>
              <span class="stat-value mono">{{ runStatus.twitter_actions_count || 0 }}</span>
            </span>
          </div>
          <!-- Available Actions Tooltip -->
          <div class="actions-tooltip">
            <div class="tooltip-title">Available Actions</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">POST</span>
              <span class="tooltip-action">LIKE</span>
              <span class="tooltip-action">REPOST</span>
              <span class="tooltip-action">QUOTE</span>
              <span class="tooltip-action">FOLLOW</span>
              <span class="tooltip-action">IDLE</span>
            </div>
          </div>
        </div>
        
        <!-- Reddit Platform Progress -->
        <div class="platform-status reddit" :class="{ active: runStatus.reddit_running, completed: runStatus.reddit_completed }">
          <div class="platform-header">
            <svg class="platform-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
            </svg>
            <span class="platform-name">Internal Forums (Email)</span>
            <span v-if="runStatus.reddit_completed" class="status-badge">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </div>
          <div class="platform-stats">
            <span class="stat">
              <span class="stat-label">ROUND</span>
              <span class="stat-value mono">{{ runStatus.reddit_current_round || 0 }}<span class="stat-total">/{{ runStatus.total_rounds || maxRounds || '-' }}</span></span>
            </span>
            <span class="stat">
              <span class="stat-label">Elapsed Time</span>
              <span class="stat-value mono">{{ redditElapsedTime }}</span>
            </span>
            <span class="stat">
              <span class="stat-label">ACTS</span>
              <span class="stat-value mono">{{ runStatus.reddit_actions_count || 0 }}</span>
            </span>
          </div>
          <!-- Available Actions Tooltip -->
          <div class="actions-tooltip">
            <div class="tooltip-title">Available Actions</div>
            <div class="tooltip-actions">
              <span class="tooltip-action">POST</span>
              <span class="tooltip-action">COMMENT</span>
              <span class="tooltip-action">LIKE</span>
              <span class="tooltip-action">DISLIKE</span>
              <span class="tooltip-action">SEARCH</span>
              <span class="tooltip-action">TREND</span>
              <span class="tooltip-action">FOLLOW</span>
              <span class="tooltip-action">MUTE</span>
              <span class="tooltip-action">REFRESH</span>
              <span class="tooltip-action">IDLE</span>
            </div>
          </div>
        </div>
      </div>

      <div class="action-controls">
        <button 
          class="action-btn primary"
          :disabled="phase !== 2 || isGeneratingReport"
          @click="handleNextStep"
        >
          <span v-if="isGeneratingReport" class="loading-spinner-small"></span>
          {{ isGeneratingReport ? 'Starting...' : 'Generate Results Report' }}
          <span v-if="!isGeneratingReport" class="arrow-icon">→</span>
        </button>
      </div>
    </div>

    <!-- Tab Switcher -->
    <div class="panel-tab-bar">
      <button class="panel-tab" :class="{ active: activeTab === 'feed' }" @click="activeTab = 'feed'">Activity Feed</button>
      <button class="panel-tab" :class="{ active: activeTab === 'tasks' }" @click="activeTab = 'tasks'">Tasks</button>
    </div>

    <!-- Tasks Panel -->
    <TaskPanel
      v-if="activeTab === 'tasks'"
      :simulationId="simulationId"
      :isSimulating="phase === 1"
      class="panel-task-view"
    />

    <!-- Main Content: Dual Timeline -->
    <div v-if="activeTab === 'feed'" class="main-content-area" ref="scrollContainer">
      <!-- Timeline Header -->
      <div class="timeline-header" v-if="chronologicalActions.length > 0">
        <div class="timeline-stats">
          <span class="total-count">TOTAL EVENTS: <span class="mono">{{ chronologicalActions.length }}</span></span>
          <span class="platform-breakdown">
            <span class="breakdown-item twitter">
              <svg class="mini-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
              <span class="mono">{{ twitterActionsCount }}</span>
            </span>
            <span class="breakdown-divider">/</span>
            <span class="breakdown-item reddit">
              <svg class="mini-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
              <span class="mono">{{ redditActionsCount }}</span>
            </span>
            <span class="breakdown-divider">/</span>
            <span class="breakdown-item task-events">
              <svg class="mini-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>
              <span class="mono">{{ taskEventsCount }}</span>
            </span>
          </span>
        </div>
      </div>
      
      <!-- Timeline Feed -->
      <div class="timeline-feed">
        <div class="timeline-axis"></div>
        
        <TransitionGroup name="timeline-item">
          <div 
            v-for="action in chronologicalActions" 
            :key="action._uniqueId || action.id || `${action.timestamp}-${action.agent_id || action.event_id}`" 
            class="timeline-item"
            :class="[action.platform || 'task', { 'task-event': isTaskEvent(action), 'mention-linked': hasMentionContext(action) }]"
          >
            <div class="timeline-marker">
              <div class="marker-dot"></div>
            </div>
            
            <div class="timeline-card">
              <div class="card-header">
                <div class="agent-info">
                  <div class="avatar-placeholder">{{ getEntryAvatar(action) }}</div>
                  <div class="agent-meta">
                    <span class="agent-name">{{ getEntryActorName(action) }}</span>
                    <span v-if="isTaskEvent(action)" class="agent-role">{{ getTaskRoutingLabel(action) }}</span>
                  </div>
                </div>
                
                <div class="header-meta">
                  <div class="platform-indicator">
                    <svg v-if="action.platform === 'twitter'" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
                    <svg v-else-if="action.platform === 'reddit'" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                    <svg v-else viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>
                  </div>
                  <div class="action-badge" :class="isTaskEvent(action) ? getTaskEventClass(action.event_type) : getActionTypeClass(action.action_type)">
                    {{ isTaskEvent(action) ? getTaskEventLabel(action.event_type) : getActionTypeLabel(action.action_type) }}
                  </div>
                </div>
              </div>
              
              <div class="card-body">
                <template v-if="isTaskEvent(action)">
                  <div class="task-title-row">
                    <span class="task-title">{{ action.task_title }}</span>
                    <span class="task-status-pill" :class="`status-${normalizeTaskStatus(action.task_status)}`">
                      {{ formatTaskStatus(action.task_status) }}
                    </span>
                  </div>

                  <div class="task-status-line">
                    {{ getTaskStatusUpdateText(action) }}
                  </div>

                  <div v-if="getTaskEventDetailChips(action).length" class="task-detail-chips">
                    <span v-for="detail in getTaskEventDetailChips(action)" :key="detail" class="task-detail-chip">
                      {{ detail }}
                    </span>
                  </div>
                </template>

                <template v-else>
                <!-- CREATE_POST: Create Post -->
                <div v-if="action.action_type === 'CREATE_POST' && action.action_args?.content" class="content-text main-text" v-html="formatHighlightedMentions(action.action_args.content)">
                </div>

                <!-- QUOTE_POST: Quote Post -->
                <template v-if="action.action_type === 'QUOTE_POST'">
                  <div v-if="action.action_args?.quote_content" class="content-text" v-html="formatHighlightedMentions(action.action_args.quote_content)">
                  </div>
                  <div v-if="action.action_args?.original_content" class="quoted-block">
                    <div class="quote-header">
                      <svg class="icon-small" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                      <span class="quote-label">@{{ action.action_args.original_author_name || 'User' }}</span>
                    </div>
                    <div class="quote-text" v-html="formatHighlightedMentions(truncateContent(action.action_args.original_content, 150))">
                    </div>
                  </div>
                </template>

                <!-- REPOST: Repost -->
                <template v-if="action.action_type === 'REPOST'">
                  <div class="repost-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"></polyline><path d="M3 11V9a4 4 0 0 1 4-4h14"></path><polyline points="7 23 3 19 7 15"></polyline><path d="M21 13v2a4 4 0 0 1-4 4H3"></path></svg>
                    <span class="repost-label">Reposted from @{{ action.action_args?.original_author_name || 'User' }}</span>
                  </div>
                  <div v-if="action.action_args?.original_content" class="repost-content">
                    {{ truncateContent(action.action_args.original_content, 200) }}
                  </div>
                </template>

                <!-- LIKE_POST: Like Post -->
                <template v-if="action.action_type === 'LIKE_POST'">
                  <div class="like-info">
                    <svg class="icon-small filled" viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                    <span class="like-label">Liked @{{ action.action_args?.post_author_name || 'User' }}'s post</span>
                  </div>
                  <div v-if="action.action_args?.post_content" class="liked-content">
                    "{{ truncateContent(action.action_args.post_content, 120) }}"
                  </div>
                </template>

                <!-- CREATE_COMMENT: Create Comment -->
                <template v-if="action.action_type === 'CREATE_COMMENT'">
                  <div v-if="action.action_args?.content" class="content-text" v-html="formatHighlightedMentions(action.action_args.content)">
                  </div>
                  <div v-if="action.action_args?.post_id" class="comment-context">
                    <svg class="icon-small" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                    <span>Reply to post #{{ action.action_args.post_id }}</span>
                  </div>
                </template>

                <!-- SEARCH_POSTS: Search Posts -->
                <template v-if="action.action_type === 'SEARCH_POSTS'">
                  <div class="search-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    <span class="search-label">Search Query:</span>
                    <span class="search-query">"{{ action.action_args?.query || '' }}"</span>
                  </div>
                </template>

                <!-- FOLLOW: Follow User -->
                <template v-if="action.action_type === 'FOLLOW'">
                  <div class="follow-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><line x1="20" y1="8" x2="20" y2="14"></line><line x1="23" y1="11" x2="17" y2="11"></line></svg>
                    <span class="follow-label">Followed @{{ action.action_args?.target_user || action.action_args?.user_id || 'User' }}</span>
                  </div>
                </template>

                <!-- UPVOTE / DOWNVOTE -->
                <template v-if="action.action_type === 'UPVOTE_POST' || action.action_type === 'DOWNVOTE_POST'">
                  <div class="vote-info">
                    <svg v-if="action.action_type === 'UPVOTE_POST'" class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"></polyline></svg>
                    <svg v-else class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    <span class="vote-label">{{ action.action_type === 'UPVOTE_POST' ? 'Upvoted' : 'Downvoted' }} Post</span>
                  </div>
                  <div v-if="action.action_args?.post_content" class="voted-content">
                    "{{ truncateContent(action.action_args.post_content, 120) }}"
                  </div>
                </template>

                <!-- DO_NOTHING: Idle (Silent) -->
                <template v-if="action.action_type === 'DO_NOTHING'">
                  <div class="idle-info">
                    <svg class="icon-small" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    <span class="idle-label">Action Skipped</span>
                  </div>
                </template>

                <!-- Generic fallback: unknown type or has content not handled above -->
                <div v-if="!['CREATE_POST', 'QUOTE_POST', 'REPOST', 'LIKE_POST', 'CREATE_COMMENT', 'SEARCH_POSTS', 'FOLLOW', 'UPVOTE_POST', 'DOWNVOTE_POST', 'DO_NOTHING'].includes(action.action_type) && action.action_args?.content" class="content-text" v-html="formatHighlightedMentions(action.action_args.content)">
                </div>

                <div v-if="getEntryMentions(action).length" class="mention-strip">
                  <span class="mention-strip-label">Mentions</span>
                  <span v-for="mention in getEntryMentions(action)" :key="mention" class="mention-chip">
                    {{ mention }}
                  </span>
                </div>
                </template>
              </div>

              <div class="card-footer">
                <span class="time-tag">R{{ action.round_num || '—' }} • {{ formatActionTime(action.timestamp) }}</span>
                <span v-if="isTaskEvent(action)" class="issue-tag">{{ action.issue_key }}</span>
              </div>
            </div>
          </div>
        </TransitionGroup>

        <div v-if="chronologicalActions.length === 0" class="waiting-state">
          <div class="pulse-ring"></div>
          <span>Waiting for agent actions...</span>
        </div>
      </div>
    </div>

    <!-- Bottom Info / Logs -->
    <div v-if="activeTab === 'feed'" class="system-logs">
      <div class="log-header">
        <span class="log-title">SIMULATION MONITOR</span>
        <span class="log-id">{{ simulationId || 'NO_SIMULATION' }}</span>
      </div>
      <div class="log-content" ref="logContent">
        <div class="log-line" v-for="(log, idx) in systemLogs" :key="idx">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.msg }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  startSimulation,
  stopSimulation,
  getRunStatus,
  getRunStatusDetail
} from '../api/simulation'
import { generateReport } from '../api/report'
import TaskPanel from './TaskPanel.vue'

const props = defineProps({
  simulationId: String,
  maxRounds: Number, // max rounds passed from Step2
  minutesPerRound: {
    type: Number,
    default: 30 // default 30 min per round
  },
  projectData: Object,
  graphData: Object,
  systemLogs: Array
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

const router = useRouter()

// State
const activeTab = ref('feed')
const isGeneratingReport = ref(false)
const phase = ref(0) // 0: not started, 1: running, 2: completed
const isStarting = ref(false)
const isStopping = ref(false)
const startError = ref(null)
const runStatus = ref({})
const allActions = ref([]) // merged action/task feed
const taskLookup = ref({})
const scrollContainer = ref(null)

// Computed
// Display actions in chronological order (newest at bottom)
const chronologicalActions = computed(() => {
  return allActions.value
})

// Platform action counts
const twitterActionsCount = computed(() => {
  return allActions.value.filter(a => !isTaskEvent(a) && a.platform === 'twitter').length
})

const redditActionsCount = computed(() => {
  return allActions.value.filter(a => !isTaskEvent(a) && a.platform === 'reddit').length
})

const taskEventsCount = computed(() => {
  return allActions.value.filter(a => a.entry_type === 'task_event').length
})

// Format simulated elapsed time (calculated from rounds and minutes per round)
const formatElapsedTime = (currentRound) => {
  if (!currentRound || currentRound <= 0) return '0h 0m'
  const totalMinutes = currentRound * props.minutesPerRound
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours}h ${minutes}m`
}

// Twitter platform simulated elapsed time
const twitterElapsedTime = computed(() => {
  return formatElapsedTime(runStatus.value.twitter_current_round || 0)
})

// Reddit platform simulated elapsed time
const redditElapsedTime = computed(() => {
  return formatElapsedTime(runStatus.value.reddit_current_round || 0)
})

// Methods
const addLog = (msg) => {
  emit('add-log', msg)
}

// Reset all state (for restarting simulation)
const resetAllState = () => {
  phase.value = 0
  runStatus.value = {}
  allActions.value = []
  taskLookup.value = {}
  prevTwitterRound.value = 0
  prevRedditRound.value = 0
  startError.value = null
  isStarting.value = false
  isStopping.value = false
  stopPolling()  // stop any existing polling
}

// Start simulation
const doStartSimulation = async () => {
  if (!props.simulationId) {
    addLog('Error: missing simulationId')
    return
  }

  // Reset all state first to avoid influence from previous simulation
  resetAllState()

  isStarting.value = true
  startError.value = null
  addLog('Starting dual-platform parallel simulation...')
  emit('update-status', 'processing')
  
  try {
    const params = {
      simulation_id: props.simulationId,
      platform: 'parallel',
      force: true,  // force restart
      enable_graph_memory_update: true  // enable dynamic graph updates
    }
    
    if (props.maxRounds) {
      params.max_rounds = props.maxRounds
      addLog(`Max simulation rounds set: ${props.maxRounds}`)
    }

    addLog('Dynamic graph update mode enabled')
    
    const res = await startSimulation(params)
    
    if (res.success && res.data) {
      if (res.data.force_restarted) {
        addLog('✓ Cleared old simulation logs, restarting simulation')
      }
      addLog('✓ Simulation engine started successfully')
      addLog(`  ├─ PID: ${res.data.process_pid || '-'}`)
      
      phase.value = 1
      runStatus.value = res.data
      
      startStatusPolling()
      startDetailPolling()
    } else {
      startError.value = res.error || 'Start failed'
      addLog(`✗ Start failed: ${res.error || 'Unknown error'}`)
      emit('update-status', 'error')
    }
  } catch (err) {
    startError.value = err.message
    addLog(`✗ Start error: ${err.message}`)
    emit('update-status', 'error')
  } finally {
    isStarting.value = false
  }
}

// Stop simulation
const handleStopSimulation = async () => {
  if (!props.simulationId) return

  isStopping.value = true
  addLog('Stopping simulation...')
  
  try {
    const res = await stopSimulation({ simulation_id: props.simulationId })
    
    if (res.success) {
      addLog('✓ Simulation stopped')
      phase.value = 2
      stopPolling()
      emit('update-status', 'completed')
    } else {
      addLog(`Stop failed: ${res.error || 'Unknown error'}`)
    }
  } catch (err) {
    addLog(`Stop error: ${err.message}`)
  } finally {
    isStopping.value = false
  }
}

// Poll status
let statusTimer = null
let detailTimer = null

const startStatusPolling = () => {
  statusTimer = setInterval(fetchRunStatus, 2000)
}

const startDetailPolling = () => {
  detailTimer = setInterval(fetchRunStatusDetail, 3000)
}

const stopPolling = () => {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
  if (detailTimer) {
    clearInterval(detailTimer)
    detailTimer = null
  }
}

// Track previous round for each platform to detect changes and output logs
const prevTwitterRound = ref(0)
const prevRedditRound = ref(0)

const fetchRunStatus = async () => {
  if (!props.simulationId) return
  
  try {
    const res = await getRunStatus(props.simulationId)
    
    if (res.success && res.data) {
      const data = res.data
      
      runStatus.value = data
      
      // Detect round changes per platform and output logs
      if (data.twitter_current_round > prevTwitterRound.value) {
        addLog(`[Plaza] R${data.twitter_current_round}/${data.total_rounds} | T:${data.twitter_simulated_hours || 0}h | A:${data.twitter_actions_count}`)
        prevTwitterRound.value = data.twitter_current_round
      }
      
      if (data.reddit_current_round > prevRedditRound.value) {
        addLog(`[Community] R${data.reddit_current_round}/${data.total_rounds} | T:${data.reddit_simulated_hours || 0}h | A:${data.reddit_actions_count}`)
        prevRedditRound.value = data.reddit_current_round
      }
      
      // Check if simulation completed (via runner_status or platform completion)
      const isCompleted = data.runner_status === 'completed' || data.runner_status === 'stopped'
      
      // Extra check: if backend hasn't updated runner_status yet, but platforms report completion
      // Detect via twitter_completed and reddit_completed status
      const platformsCompleted = checkPlatformsCompleted(data)
      
      if (isCompleted || platformsCompleted) {
        if (platformsCompleted && !isCompleted) {
          addLog('✓ All platform simulations detected as completed')
        }
        addLog('✓ Simulation completed')
        phase.value = 2
        stopPolling()
        emit('update-status', 'completed')
      }
    }
  } catch (err) {
    console.warn('Failed to fetch run status:', err)
  }
}

// Check if all enabled platforms have completed
const checkPlatformsCompleted = (data) => {
  // If no platform data, return false
  if (!data) return false
  
  // Check completion status of each platform
  const twitterCompleted = data.twitter_completed === true
  const redditCompleted = data.reddit_completed === true
  
  // If at least one platform completed, check if all enabled platforms completed
  // Determine if platform is enabled via actions_count (if count > 0 or running was true)
  const twitterEnabled = (data.twitter_actions_count > 0) || data.twitter_running || twitterCompleted
  const redditEnabled = (data.reddit_actions_count > 0) || data.reddit_running || redditCompleted
  
  // If no platforms are enabled, return false
  if (!twitterEnabled && !redditEnabled) return false
  
  // Check if all enabled platforms have completed
  if (twitterEnabled && !twitterCompleted) return false
  if (redditEnabled && !redditCompleted) return false
  
  return true
}

const fetchRunStatusDetail = async () => {
  if (!props.simulationId) return
  
  try {
    const res = await getRunStatusDetail(props.simulationId, {
      include_tasks: true,
      include_task_events: true,
      include_merged_feed: true
    })
    
    if (res.success && res.data) {
      const nextTaskLookup = {}
      ;(res.data.tasks || []).forEach(task => {
        nextTaskLookup[task.issue_key] = task
      })
      taskLookup.value = nextTaskLookup

      const serverFeed = res.data.merged_feed || res.data.all_actions || []
      allActions.value = serverFeed.map(entry => ({
        ...entry,
        _uniqueId: buildFeedEntryId(entry)
      }))
    }
  } catch (err) {
    console.warn('Failed to fetch detailed status:', err)
  }
}

// Helpers
const MENTION_RE = /@[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}/g

const isTaskEvent = (entry) => entry?.entry_type === 'task_event'

const buildFeedEntryId = (entry) => {
  if (entry?.entry_type === 'task_event') {
    return entry.event_id || `${entry.issue_key}-${entry.event_type}-${entry.timestamp}`
  }
  return entry?.id || `${entry?.timestamp}-${entry?.platform}-${entry?.agent_id}-${entry?.action_type}`
}

const getTaskForEntry = (entry) => {
  return taskLookup.value[entry?.issue_key] || null
}

const getEntryActorName = (entry) => {
  if (isTaskEvent(entry)) {
    return entry.actor || entry.assigned_to || entry.assigned_by || 'Task'
  }
  return entry.agent_name || 'Agent'
}

const getEntryAvatar = (entry) => {
  const label = getEntryActorName(entry)
  return (label || 'A').charAt(0)
}

const getTaskRoutingLabel = (entry) => {
  const from = entry.assigned_by || 'Unknown'
  const to = entry.assigned_to || 'Unassigned'
  return `${from} → ${to}`
}

const normalizeTaskStatus = (status) => {
  return String(status || 'open').toLowerCase().replace(/[^a-z0-9]+/g, '_')
}

const formatTaskStatus = (status) => {
  return String(status || 'open')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase())
}

const getTaskEventLabel = (eventType) => {
  const labels = {
    created: 'Offered',
    offered: 'Offered',
    accepted: 'Accepted',
    declined: 'Declined',
    started: 'Started',
    blocked: 'Blocked',
    completed: 'Completed',
    expired: 'Expired',
    progress_updated: 'Progress',
    status_updated: 'Updated',
    public_update: 'Chat Update',
    artifact_saved: 'Artifact',
    artifact_added: 'Artifact',
    artifact_removed: 'Artifact',
    updated: 'Updated'
  }
  return labels[eventType] || String(eventType || 'task').replace(/_/g, ' ')
}

const getTaskEventClass = (eventType) => {
  const classes = {
    created: 'badge-task-offered',
    offered: 'badge-task-offered',
    accepted: 'badge-task-active',
    started: 'badge-task-active',
    progress_updated: 'badge-task-active',
    blocked: 'badge-task-blocked',
    completed: 'badge-task-done',
    declined: 'badge-task-muted',
    expired: 'badge-task-muted',
    public_update: 'badge-task-meta',
    status_updated: 'badge-task-meta',
    artifact_saved: 'badge-task-meta',
    artifact_added: 'badge-task-meta',
    artifact_removed: 'badge-task-meta',
    updated: 'badge-task-meta'
  }
  return classes[eventType] || 'badge-task-meta'
}

const escapeHtml = (value) => {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const formatHighlightedMentions = (value) => {
  const escaped = escapeHtml(value)
  return escaped.replace(MENTION_RE, match => `<mark class="mention-inline">${match}</mark>`)
}

const extractMentions = (value) => {
  const matches = String(value || '').match(MENTION_RE) || []
  return [...new Set(matches)]
}

const getEntryMentions = (entry) => {
  if (isTaskEvent(entry)) {
    const mentionSnippet = getTaskMentionSnippet(entry)
    return extractMentions(mentionSnippet)
  }

  const contentCandidates = [
    entry?.action_args?.content,
    entry?.action_args?.quote_content,
    entry?.action_args?.original_content,
    entry?.action_args?.post_content
  ]

  return [...new Set(contentCandidates.flatMap(candidate => extractMentions(candidate)))]
}

const getTaskMentionSnippet = (entry) => {
  const task = getTaskForEntry(entry)
  return task?.mention_context?.snippet || task?.origin_metadata?.public_text || ''
}

const hasMentionContext = (entry) => {
  return getEntryMentions(entry).length > 0
}

const getTaskStatusUpdateText = (entry) => {
  const publicUpdate = (entry?.public_update || entry?.details?.public_update || '').trim()
  if (publicUpdate) {
    return publicUpdate
  }

  const actor = entry?.actor || entry?.assigned_to || 'Agent'
  const issueKey = entry?.issue_key || 'task'

  const labels = {
    offered: `${actor} offered ${issueKey}.`,
    accepted: `${actor} accepted ${issueKey}.`,
    declined: `${actor} declined ${issueKey}.`,
    started: `${actor} started ${issueKey}.`,
    blocked: `${actor} marked ${issueKey} as blocked.`,
    completed: `${actor} completed ${issueKey}.`,
    expired: `${issueKey} expired.`,
    progress_updated: `${actor} posted a progress update for ${issueKey}.`,
    status_updated: `${actor} updated the status for ${issueKey}.`,
    public_update: `${actor} posted a task-linked chat update for ${issueKey}.`,
    artifact_saved: `${actor} added an artifact to ${issueKey}.`,
    artifact_added: `${actor} added an artifact to ${issueKey}.`,
    artifact_removed: `${actor} removed an artifact from ${issueKey}.`,
    updated: `${actor} updated ${issueKey}.`
  }

  return labels[entry?.event_type] || `${actor} updated ${issueKey}.`
}

const getTaskEventDetailChips = (entry) => {
  const details = entry?.details || {}
  const chips = []

  const artifactCount = details.artifact_count ?? entry?.artifact_summaries?.length

  if (details.due_round != null) {
    chips.push(`Due R${details.due_round}`)
  }
  if (details.round_budget != null) {
    chips.push(`${details.round_budget}r budget`)
  }
  if (artifactCount != null) {
    chips.push(`${artifactCount} artifacts`)
  }
  if (entry?.round_num != null) {
    chips.push(`R${entry.round_num}`)
  }

  return chips
}

const getActionTypeLabel = (type) => {
  const labels = {
    'CREATE_POST': 'POST',
    'REPOST': 'REPOST',
    'LIKE_POST': 'LIKE',
    'CREATE_COMMENT': 'COMMENT',
    'LIKE_COMMENT': 'LIKE',
    'DO_NOTHING': 'IDLE',
    'FOLLOW': 'FOLLOW',
    'SEARCH_POSTS': 'SEARCH',
    'QUOTE_POST': 'QUOTE',
    'UPVOTE_POST': 'UPVOTE',
    'DOWNVOTE_POST': 'DOWNVOTE'
  }
  return labels[type] || type || 'UNKNOWN'
}

const getActionTypeClass = (type) => {
  const classes = {
    'CREATE_POST': 'badge-post',
    'REPOST': 'badge-action',
    'LIKE_POST': 'badge-action',
    'CREATE_COMMENT': 'badge-comment',
    'LIKE_COMMENT': 'badge-action',
    'QUOTE_POST': 'badge-post',
    'FOLLOW': 'badge-meta',
    'SEARCH_POSTS': 'badge-meta',
    'UPVOTE_POST': 'badge-action',
    'DOWNVOTE_POST': 'badge-action',
    'DO_NOTHING': 'badge-idle'
  }
  return classes[type] || 'badge-default'
}

const truncateContent = (content, maxLength = 100) => {
  if (!content) return ''
  if (content.length > maxLength) return content.substring(0, maxLength) + '...'
  return content
}

const formatActionTime = (timestamp) => {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

const handleNextStep = async () => {
  if (!props.simulationId) {
    addLog('Error: missing simulationId')
    return
  }

  if (isGeneratingReport.value) {
    addLog('Report generation request already sent, please wait...')
    return
  }

  isGeneratingReport.value = true
  addLog('Starting report generation...')
  
  try {
    const res = await generateReport({
      simulation_id: props.simulationId,
      force_regenerate: true
    })
    
    if (res.success && res.data) {
      const reportId = res.data.report_id
      addLog(`✓ Report generation task started: ${reportId}`)

      // Navigate to report page
      router.push({ name: 'Report', params: { reportId } })
    } else {
      addLog(`✗ Failed to start report generation: ${res.error || 'Unknown error'}`)
      isGeneratingReport.value = false
    }
  } catch (err) {
    addLog(`✗ Report generation error: ${err.message}`)
    isGeneratingReport.value = false
  }
}

// Scroll log to bottom
const logContent = ref(null)
watch(() => props.systemLogs?.length, () => {
  nextTick(() => {
    if (logContent.value) {
      logContent.value.scrollTop = logContent.value.scrollHeight
    }
  })
})

onMounted(() => {
  addLog('Step3 simulation run initializing')
  if (props.simulationId) {
    doStartSimulation()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.simulation-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  font-family: 'Inter', system-ui, sans-serif;
  overflow: hidden;
}

/* --- Control Bar --- */
.control-bar {
  background: var(--bg-primary);
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-color);
  z-index: 10;
  height: 64px;
}

.status-group {
  display: flex;
  gap: 12px;
}

/* Platform Status Cards */
.platform-status {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 4px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  opacity: 0.7;
  transition: all 0.3s;
  min-width: 140px;
  position: relative;
  cursor: pointer;
}

.platform-status.active {
  opacity: 1;
  border-color: var(--text-primary);
  background: var(--bg-primary);
}

.platform-status.completed {
  opacity: 1;
  border-color: var(--accent-color, #1A936F);
  background: var(--bg-secondary);
}

/* Actions Tooltip */
.actions-tooltip {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-top: 8px;
  padding: 10px 14px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s ease;
  z-index: 100;
  min-width: 180px;
  pointer-events: none;
}

.actions-tooltip::before {
  content: '';
  position: absolute;
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-bottom: 6px solid var(--border-color);
}

.platform-status:hover .actions-tooltip {
  opacity: 1;
  visibility: visible;
}

.tooltip-title {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
}

.tooltip-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tooltip-action {
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 2px;
  color: var(--text-primary);
  letter-spacing: 0.03em;
}

.platform-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
}

.platform-name {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.platform-status.twitter .platform-icon { color: var(--text-primary); }
.platform-status.reddit .platform-icon { color: var(--text-primary); }

.platform-stats {
  display: flex;
  gap: 10px;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 3px;
}

.stat-label {
  font-size: 8px;
  color: var(--text-muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.task-status-line {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
}

.stat-total, .stat-unit {
  font-size: 9px;
  color: var(--text-muted);
  font-weight: 400;
}

.status-badge {
  margin-left: auto;
  color: var(--accent-color, #1A936F);
  display: flex;
  align-items: center;
}

/* Action Button */
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.action-btn.primary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.action-btn.primary:hover:not(:disabled) {
  background: var(--bg-secondary);
}

.action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* --- Main Content Area --- */
.main-content-area {
  flex: 1;
  overflow-y: auto;
  position: relative;
  background: var(--bg-primary);
}

/* Timeline Header */
.timeline-header {
  position: sticky;
  top: 0;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(8px);
  padding: 12px 24px;
  border-bottom: 1px solid var(--border-color);
  z-index: 5;
  display: flex;
  justify-content: center;
}

.timeline-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  padding: 4px 12px;
  border-radius: 20px;
}

.total-count {
  font-weight: 600;
  color: var(--text-primary);
}

.platform-breakdown {
  display: flex;
  align-items: center;
  gap: 8px;
}

.breakdown-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.breakdown-divider { color: var(--text-secondary); }
.breakdown-item.twitter { color: var(--text-primary); }
.breakdown-item.reddit { color: var(--text-primary); }

/* --- Timeline Feed --- */
.timeline-feed {
  padding: 24px 0;
  position: relative;
  min-height: 100%;
  max-width: 900px;
  margin: 0 auto;
}

.timeline-axis {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-color); /* Cleaner line */
  transform: translateX(-50%);
}

.timeline-item {
  display: flex;
  justify-content: center;
  margin-bottom: 32px;
  position: relative;
  width: 100%;
}

.timeline-marker {
  position: absolute;
  left: 50%;
  top: 24px;
  width: 10px;
  height: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 50%;
  transform: translateX(-50%);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
}

.marker-dot {
  width: 4px;
  height: 4px;
  background: var(--text-muted);
  border-radius: 50%;
}

.timeline-item.twitter .marker-dot { background: var(--bg-tertiary); }
.timeline-item.reddit .marker-dot { background: var(--bg-tertiary); }
.timeline-item.twitter .timeline-marker { border-color: var(--text-primary); }
.timeline-item.reddit .timeline-marker { border-color: var(--text-primary); }
.timeline-item.task .marker-dot,
.timeline-item.task-event .marker-dot { background: var(--text-primary); }
.timeline-item.task .timeline-marker,
.timeline-item.task-event .timeline-marker { border-color: var(--text-primary); }

/* Card Layout */
.timeline-card {
  width: calc(100% - 48px);
  background: var(--bg-primary);
  border-radius: 2px;
  padding: 16px 20px;
  border: 1px solid var(--border-color);
  box-shadow: 0 2px 10px rgba(0,0,0,0.02);
  position: relative;
  transition: all 0.2s;
}

.timeline-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  border-color: var(--border-color);
}

/* Left side (Twitter) */
.timeline-item.twitter {
  justify-content: flex-start;
  padding-right: 50%;
}
.timeline-item.twitter .timeline-card {
  margin-left: auto;
  margin-right: 32px; /* Gap from axis */
}

/* Right side (Reddit) */
.timeline-item.reddit {
  justify-content: flex-end;
  padding-left: 50%;
}
.timeline-item.reddit .timeline-card {
  margin-right: auto;
  margin-left: 32px; /* Gap from axis */
}

/* Task events remain centered but use the left rail for continuity */
.timeline-item.task,
.timeline-item.task-event {
  justify-content: flex-start;
  padding-right: 50%;
}

.timeline-item.task .timeline-card,
.timeline-item.task-event .timeline-card {
  margin-left: auto;
  margin-right: 32px;
  border-style: dashed;
}

.timeline-item.mention-linked .timeline-card {
  box-shadow: 0 0 0 1px rgba(0,0,0,0.06);
}

/* Card Content Styles */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-secondary);
}

.agent-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.agent-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.avatar-placeholder {
  width: 24px;
  height: 24px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.agent-role {
  font-size: 10px;
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', monospace;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.platform-indicator {
  color: var(--text-muted);
  display: flex;
  align-items: center;
}

.action-badge {
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 2px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border: 1px solid transparent;
}

/* Monochromatic Badges */
.badge-post { background: var(--border-color); color: var(--text-primary); border-color: var(--border-color); }
.badge-comment { background: var(--border-color); color: var(--text-secondary); border-color: var(--border-color); }
.badge-action { background: var(--bg-primary); color: var(--text-secondary); border: 1px solid var(--border-color); }
.badge-meta { background: var(--bg-secondary); color: var(--text-muted); border: 1px dashed var(--border-color); }
.badge-idle { opacity: 0.5; }
.badge-task-offered { background: var(--bg-secondary); color: var(--text-primary); border: 1px dashed var(--text-primary); }
.badge-task-active { background: var(--border-color); color: var(--text-primary); border-color: var(--border-color); }
.badge-task-blocked { background: var(--bg-secondary); color: var(--text-secondary); border-color: var(--border-color); }
.badge-task-done { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--text-primary); }
.badge-task-muted { background: var(--bg-primary); color: var(--text-muted); border: 1px solid var(--border-color); }
.badge-task-meta { background: var(--bg-secondary); color: var(--text-secondary); border: 1px dashed var(--border-color); }

.content-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.content-text.main-text {
  font-size: 14px;
  color: var(--text-primary);
}

:deep(.mention-inline) {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  padding: 0 3px;
  border-radius: 2px;
}

.task-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
}

.task-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.task-status-pill {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.task-status-pill.status-offered,
.task-status-pill.status-open { border-style: dashed; color: var(--text-primary); }
.task-status-pill.status-in_progress { color: var(--text-primary); background: var(--bg-secondary); }
.task-status-pill.status-blocked { color: var(--text-secondary); }
.task-status-pill.status-done { color: var(--text-primary); background: var(--bg-tertiary); }
.task-status-pill.status-declined,
.task-status-pill.status-expired { color: var(--text-muted); }

.task-event-summary {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.mention-context {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  margin-bottom: 10px;
}

.mention-context-label,
.mention-strip-label,
.task-artifact-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}

.mention-context-text {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-primary);
}

.mention-strip,
.task-detail-chips,
.task-artifact-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
}

.mention-chip,
.task-detail-chip,
.task-artifact-chip,
.issue-tag {
  font-size: 10px;
  padding: 3px 7px;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  background: var(--bg-secondary);
}

/* Info Blocks (Quote, Repost, etc) */
.quoted-block, .repost-content {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  padding: 10px 12px;
  border-radius: 2px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-primary);
}

.quote-header, .repost-info, .like-info, .search-info, .follow-info, .vote-info, .idle-info, .comment-context {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}

.icon-small {
  color: var(--text-muted);
}
.icon-small.filled {
  color: var(--text-muted); /* Keep icons neutral unless highlighted */
}

.search-query {
  font-family: 'JetBrains Mono', monospace;
  background: var(--border-color);
  padding: 0 4px;
  border-radius: 2px;
}

.card-footer {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 10px;
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', monospace;
}

/* Waiting State */
.waiting-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: var(--text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.pulse-ring {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  animation: ripple 2s infinite;
}

@keyframes ripple {
  0% { transform: scale(0.8); opacity: 1; border-color: var(--border-color); }
  100% { transform: scale(2.5); opacity: 0; border-color: var(--border-color); }
}

/* Animation */
.timeline-item-enter-active,
.timeline-item-leave-active {
  transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
}

.timeline-item-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.timeline-item-leave-to {
  opacity: 0;
}

/* Logs */
.system-logs {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  padding: 16px;
  font-family: 'JetBrains Mono', monospace;
  border-top: 1px solid var(--text-primary);
  flex-shrink: 0;
}

.log-header {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 8px;
  margin-bottom: 8px;
  font-size: 10px;
  color: var(--text-secondary);
}

.log-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100px;
  overflow-y: auto;
  padding-right: 4px;
}

.log-content::-webkit-scrollbar { width: 4px; }
.log-content::-webkit-scrollbar-thumb { background: var(--bg-secondary); border-radius: 2px; }

.log-line {
  font-size: 11px;
  display: flex;
  gap: 12px;
  line-height: 1.5;
}

.log-time { color: var(--text-primary); min-width: 75px; }
.log-msg { color: var(--text-secondary); word-break: break-all; }
.mono { font-family: 'JetBrains Mono', monospace; }

/* Loading spinner for button */
.loading-spinner-small {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: var(--text-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-right: 6px;
}

/* --- Panel Tab Bar --- */
.panel-tab-bar {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
  padding: 0 24px;
  flex-shrink: 0;
}

.panel-tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 10px 16px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  transition: all 0.2s;
  margin-bottom: -1px;
}

.panel-tab:hover {
  color: var(--text-primary);
}

.panel-tab.active {
  color: var(--text-primary);
  border-bottom-color: var(--text-primary);
}

.panel-task-view {
  flex: 1;
  overflow-y: auto;
}
</style>