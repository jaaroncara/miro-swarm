/**
 * Temporary storage for pending file uploads and requirements.
 * Used when launching the engine from the homepage - stores data
 * before navigating to Process page where the API call is made.
 *
 * File objects are kept in-memory (they can't be serialised), while the
 * metadata & requirement are mirrored to sessionStorage so the intent
 * survives an accidental page-reload on /process/new.
 */
import { reactive } from 'vue'

const STORAGE_KEY = 'mirofish_pending_upload'

// --- helpers -----------------------------------------------------------
function _saveMetadata() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      fileNames: state.files.map(f => f.name),
      simulationRequirement: state.simulationRequirement,
      isPending: state.isPending
    }))
  } catch { /* quota / private-browsing – not critical */ }
}

function _loadMetadata() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function _clearMetadata() {
  try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* noop */ }
}

// --- state -------------------------------------------------------------
const state = reactive({
  files: [],
  simulationRequirement: '',
  isPending: false
})

// Restore requirement (but NOT files – those must come from a real input)
const _restored = _loadMetadata()
if (_restored && _restored.isPending) {
  state.simulationRequirement = _restored.simulationRequirement || ''
  // isPending stays false until files are provided again
}

// --- public API --------------------------------------------------------
export function setPendingUpload(files, requirement) {
  state.files = Array.from(files) // ensure a plain array copy
  state.simulationRequirement = requirement
  state.isPending = true
  _saveMetadata()
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    isPending: state.isPending
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.isPending = false
  _clearMetadata()
}

export default state
