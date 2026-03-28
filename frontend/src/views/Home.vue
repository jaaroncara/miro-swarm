<template>
  <div class="home-container">
    <nav class="navbar">
      <div class="nav-brand">SWARM ANALYTICS</div>
      <div class="nav-links">
        <a href="https://github.com/jaaroncara" target="_blank" class="github-link">
          @github <span class="arrow">↗</span>
        </a>
      </div>
    </nav>

    <div class="main-content">
      <section class="hero-section">
        <div class="hero-content">
          <img src="/icon.png" alt="Swarm Analytics Logo" class="hero-logo" />
          <h1 class="main-title">ABIE.ai</h1>
          <p class="subtitle"><b>Agentic Business Intelligence Engine</b></p>
          <p class="subtitle">Upload reports. Describe scenarios. Simulate outcomes.</p>
        </div>
      </section>

      <section class="dashboard-section">
        <div class="console-wrapper">
          <div class="console-box">
            <!-- Reports Section -->
            <div class="console-section">
              <div class="console-header">
                <span class="console-label">01 /// Business Reports</span>
                <span class="console-meta">Supported formats: PDF, MD, TXT</span>
              </div>
              
              <div class="upload-zone"
                   :class="{ 'drag-over': isDragOver, 'has-files': files.length > 0 }"
                   @dragover.prevent="handleDragOver"
                   @dragleave.prevent="handleDragLeave"
                   @drop.prevent="handleDrop"
                   @click="triggerFileInput">
                
                <input ref="fileInput" type="file" multiple accept=".pdf,.md,.txt"
                       @change="handleFileSelect" style="display: none" :disabled="loading" />
                
                <div v-if="files.length === 0" class="upload-placeholder">
                  <div class="upload-icon">↑</div>
                  <div class="upload-title">Drag & drop files to upload</div>
                  <div class="upload-hint">or click to browse file system</div>
                </div>
                
                <div v-else class="file-list">
                  <div v-for="(file, index) in files" :key="index" class="file-item">
                    <span class="file-icon">📄</span>
                    <span class="file-name">{{ file.name }}</span>
                    <button @click.stop="removeFile(index)" class="remove-btn">×</button>
                  </div>
                </div>
              </div>
            </div>

            <div class="console-divider"><span>Input Parameters</span></div>

            <!-- Simulation Parameters Section -->
            <div class="console-section">
              <div class="console-header">
                <span class="console-label">02 /// Simulation Prompt</span>
              </div>
              <div class="input-wrapper">
                <textarea
                  v-model="formData.simulationRequirement"
                  class="code-input"
                  placeholder="e.g. If adidas launches a new type of gift-with-purchase promotion, how should the brand marketing strategy adapt given the current business performance?"
                  rows="6"
                  :disabled="loading"
                ></textarea>
              </div>
            </div>

            <!-- Error Display -->
            <div v-if="error" class="console-section error-section">
              <div class="error-message">⚠ {{ error }}</div>
            </div>

            <!-- Submit Section -->
            <div class="console-section btn-section">
              <button class="start-engine-btn" @click="startSimulation" :disabled="!canSubmit || loading">
                <span v-if="!loading">Launch Simulation</span>
                <span v-else>Generating Ontology...</span>
                <span class="btn-arrow">→</span>
              </button>
            </div>
          </div>
        </div>
      </section>
      
      <!-- History Section below dashboard -->
      <HistoryDatabase />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import { generateOntology } from '../api/graph'

const router = useRouter()

// Form data
const formData = ref({
  simulationRequirement: ''
})

// File list
const files = ref([])

// State
const loading = ref(false)
const error = ref('')
const isDragOver = ref(false)

// File input ref
const fileInput = ref(null)

// Computed: whether form can be submitted
const canSubmit = computed(() => {
  return formData.value.simulationRequirement.trim() !== '' && files.value.length > 0
})

// Trigger file selection
const triggerFileInput = () => {
  if (!loading.value) {
    fileInput.value?.click()
  }
}

// Handle file selection
const handleFileSelect = (event) => {
  const selectedFiles = Array.from(event.target.files)
  addFiles(selectedFiles)
}

// Handle drag events
const handleDragOver = (e) => {
  if (!loading.value) {
    isDragOver.value = true
  }
}

const handleDragLeave = (e) => {
  isDragOver.value = false
}

const handleDrop = (e) => {
  isDragOver.value = false
  if (loading.value) return
  
  const droppedFiles = Array.from(e.dataTransfer.files)
  addFiles(droppedFiles)
}

// Add files
const addFiles = (newFiles) => {
  const validFiles = newFiles.filter(file => {
    const ext = file.name.split('.').pop().toLowerCase()
    return ['pdf', 'md', 'txt'].includes(ext)
  })
  files.value.push(...validFiles)
}

// Remove file
const removeFile = (index) => {
  files.value.splice(index, 1)
}

// Scroll to bottom
const scrollToBottom = () => {
  window.scrollTo({
    top: document.body.scrollHeight,
    behavior: 'smooth'
  })
}

// Debug beacon helper
const _b = (step, detail = '') => {
  try { navigator.sendBeacon('/api/debug/beacon', JSON.stringify({ step, detail })) } catch {}
  try { fetch('/api/debug/beacon', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ step, detail }) }).catch(() => {}) } catch {}
}

// Start simulation - upload files and call ontology API directly, then navigate
const startSimulation = async () => {
  if (!canSubmit.value || loading.value) return

  loading.value = true
  error.value = ''
  _b('1-startSimulation', `files=${files.value.length}`)

  try {
    // Build form data with files + requirement
    const fd = new FormData()
    files.value.forEach(f => fd.append('files', f))
    fd.append('simulation_requirement', formData.value.simulationRequirement)

    _b('2-callingAPI')

    // Call ontology generation API directly (no fragile in-memory handoff)
    const res = await generateOntology(fd)

    _b('3-apiReturned', `success=${res?.success} hasData=${!!res?.data} projectId=${res?.data?.project_id}`)

    if (res.success && res.data?.project_id) {
      const pid = res.data.project_id
      _b('4-navigating', pid)
      // Navigate to Process page with the real project ID
      router.push({
        name: 'Process',
        params: { projectId: pid }
      }).then(() => {
        _b('5-navSuccess', pid)
      }).catch(err => {
        _b('5-navFailed', String(err))
        console.error('Navigation failed:', err)
        error.value = 'Ontology generated but navigation failed. Project ID: ' + pid
        loading.value = false
      })
    } else {
      _b('4-ontologyFail', res?.error || 'no success')
      error.value = res.error || 'Ontology generation failed – please try again.'
      loading.value = false
    }
  } catch (err) {
    _b('CATCH', String(err))
    console.error('Failed to launch simulation:', err)
    error.value = err.response?.data?.error || err.message || 'Failed to launch – please try again.'
    loading.value = false
  }
}
</script>

<style scoped>
:root {
  --bg-color: #000000;
  --surface-color: #111111;
  --border-color: #333333;
  --text-primary: #ffffff;
  --text-secondary: #888888;
  --accent-color: #ffffff;
  --accent-hover: #cccccc;
  --error: #ff4444;
}

.home-container {
  min-height: 100vh;
  background-color: var(--bg-color);
  color: var(--text-primary);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  display: flex;
  flex-direction: column;
}

.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 2rem;
  border-bottom: 1px solid var(--border-color);
  background-color: var(--bg-color);
}

.nav-brand {
  font-size: 0.85rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--text-primary);
}

.github-link {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  transition: color 0.2s ease;
}

.github-link:hover {
  color: var(--text-primary);
}

.arrow {
  font-family: monospace;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 4rem 2rem;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.hero-section {
  text-align: center;
  margin-bottom: 4rem;
}

.hero-logo {
  width: 80px;
  height: auto;
  margin-bottom: 1.5rem;
}

.main-title {
  font-size: 3.5rem;
  font-weight: 500;
  line-height: 1.1;
  margin-bottom: 1rem;
  letter-spacing: -0.02em;
}

.subtitle {
  font-size: 1.1rem;
  color: var(--text-secondary);
  max-width: 600px;
  margin: 0 auto;
  line-height: 1.5;
}

.dashboard-section {
  display: flex;
  justify-content: center;
  margin-bottom: 4rem;
}

.console-wrapper {
  width: 100%;
  max-width: 800px;
}

.console-box {
  background: var(--surface-color);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 20px 40px rgba(0,0,0,0.4);
}

.console-section {
  padding: 2rem;
}

.console-divider {
  display: flex;
  align-items: center;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}

.console-divider::before,
.console-divider::after {
  content: '';
  flex: 1;
  border-bottom: 1px solid var(--border-color);
}

.console-divider span {
  padding: 0 1rem;
}

.console-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
}

.console-label {
  color: var(--text-primary);
}

.console-meta {
  color: var(--text-secondary);
}

.upload-zone {
  border: 1px dashed var(--border-color);
  border-radius: 6px;
  padding: 3rem 2rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  background: rgba(255, 255, 255, 0.02);
}

.upload-zone:hover, .upload-zone.drag-over {
  border-color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.upload-icon {
  font-size: 1.5rem;
  margin-bottom: 1rem;
  color: var(--text-secondary);
}

.upload-title {
  font-size: 1rem;
  margin-bottom: 0.5rem;
  color: var(--text-primary);
}

.upload-hint {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.file-list {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.file-item {
  display: flex;
  align-items: center;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  border: 1px solid var(--border-color);
}

.file-icon {
  margin-right: 1rem;
}

.file-name {
  flex: 1;
  font-size: 0.9rem;
  font-family: 'JetBrains Mono', monospace;
}

.remove-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 1.2rem;
}

.remove-btn:hover {
  color: var(--error);
}

.input-wrapper {
  margin-top: 1rem;
}

.code-input {
  width: 100%;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 1rem;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
  line-height: 1.5;
  resize: vertical;
  min-height: 120px;
}

.code-input:focus {
  outline: none;
  border-color: var(--text-primary);
}

.error-section {
  background: rgba(255, 80, 80, 0.08);
  border-top: 1px solid rgba(255, 80, 80, 0.3);
}

.error-message {
  color: #ff5050;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.85rem;
  padding: 0.5rem 0;
}

.btn-section {
  display: flex;
  justify-content: flex-end;
  background: rgba(255, 255, 255, 0.02);
  border-top: 1px solid var(--border-color);
}

.start-engine-btn {
  background: #000000;
  color: var(--bg-color);
  border: none;
  padding: 0.75rem 2rem;
  border-radius: 4px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  transition: all 0.2s ease;
}

.start-engine-btn:hover:not(:disabled) {
  background: var(--accent-hover);
  transform: translateY(-1px);
}

.start-engine-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .main-content {
    padding: 2rem 1rem;
  }
  
  .main-title {
    font-size: 2.5rem;
  }
  
  .console-section {
    padding: 1.5rem;
  }
}
</style>
