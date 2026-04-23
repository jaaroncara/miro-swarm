import service, { requestWithRetry } from './index'

/**
 * Start report generation
 * @param {Object} data - { simulation_id, force_regenerate? }
 */
export const generateReport = (data) => {
  return requestWithRetry(() => service.post('/api/report/generate', data), 3, 1000)
}

/**
 * Get report generation status
 * @param {string|Object} input - reportId string or { task_id?, simulation_id?, report_id? }
 */
export const getReportStatus = (input) => {
  const params = typeof input === 'string' ? { report_id: input } : (input || {})
  return service.get(`/api/report/generate/status`, { params })
}

/**
 * Get Agent log (incremental)
 * @param {string} reportId
 * @param {number} fromLine - Starting line number
 */
export const getAgentLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/agent-log`, { params: { from_line: fromLine } })
}

/**
 * Get console log (incremental)
 * @param {string} reportId
 * @param {number} fromLine - Starting line number
 */
export const getConsoleLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/console-log`, { params: { from_line: fromLine } })
}

/**
 * Get report details
 * @param {string} reportId
 */
export const getReport = (reportId) => {
  return service.get(`/api/report/${reportId}`)
}

/**
 * Chat with Report Agent
 * @param {Object} data - { simulation_id, message, chat_history?, task_ref? }
 */
export const chatWithReport = (data) => {
  return requestWithRetry(() => service.post('/api/report/chat', data), 3, 1000)
}

/**
 * Get packaged report deliverables manifest
 * @param {string} reportId
 */
export const getReportDeliverables = (reportId) => {
  return service.get(`/api/report/${reportId}/deliverables`)
}
