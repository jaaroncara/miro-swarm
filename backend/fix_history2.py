import re

with open('src/components/HistoryDatabase.vue', 'r') as f:
    content = f.read()

# 1. Remove tech grid
content = re.sub(r'<!-- Background decoration.*?</style>', lambda m: m.group().replace('<div v-if="projects.length > 0 || loading" class="tech-grid-bg">', '<!-- <div class="tech-grid-bg">'), content, flags=re.DOTALL)
content = re.sub(r'<div v-if="projects\.length > 0 \|\| loading" class="tech-grid-bg">.*?</div>\s*</div>', '', content, flags=re.DOTALL)

# 2. Simplify container
content = content.replace(
    '<div v-if="projects.length > 0" class="cards-container" :class="{ expanded: isExpanded }" :style="containerStyle">',
    '<div v-if="projects.length > 0" class="cards-container">'
)

# 3. Simplify project-card
content = re.sub(
    r'<div\s+v-for="\(project, index\) in projects"\s+:key="project\.simulation_id"\s+class="project-card"\s+:class="\{ expanded: isExpanded, hovering: hoveringCard === index \}"\s+:style="getCardStyle\(index\)"\s+@mouseenter="hoveringCard = index"\s+@mouseleave="hoveringCard = null"\s+@click="navigateToProject\(project\)"\s*>',
    r'''<div 
        v-for="(project, index) in projects" 
        :key="project.simulation_id"
        class="project-card"
        @click="navigateToProject(project)"
      >
        <!-- Delete Button -->
        <button class="delete-project-btn" @click.stop="handleDeleteProject(project)" title="Delete Project">
          <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
        </button>''',
    content
)

# 4. Add script logic
script_replacement = """
import { deleteProject } from '../api/graph'

// Handle delete project
const handleDeleteProject = async (project) => {
  if (confirm(`Are you sure you want to delete prediction ${formatSimulationId(project.simulation_id)}?`)) {
    try {
      loading.value = true
      // We pass the project_id if it exists, otherwise we'd need a delete simulation endpoint.
      if (project.project_id) {
         await deleteProject(project.project_id)
      }
      // Reload logic
      await loadHistory()
    } catch (e) {
      console.error(e)
      alert("Failed to delete project.")
    } finally {
      loading.value = false
    }
  }
}
"""
content = re.sub(r"const router = useRouter\(\)", script_replacement + "\nconst router = useRouter()", content)
content = content.replace("import { getSimulationHistory } from '../api/simulation'", "import { getSimulationHistory } from '../api/simulation'\nimport { deleteProject } from '../api/graph'")

# 5. Remove all Observer and Expand logic footprint
content = re.sub(r'const isExpanded = ref\(false\).*?const containerStyle = computed\(\(\) => \{.+?\}\)(?:\n|$)', '', content, flags=re.DOTALL)
content = re.sub(r'const getCardStyle = \(index\) => \{.+?\}\n\n// Get style class', '// Get style class', content, flags=re.DOTALL)
content = re.sub(r'// Initialize IntersectionObserver.+?\}\n\n// Watch route changes', '// Watch route changes', content, flags=re.DOTALL)
content = re.sub(r'setTimeout\(\(\) => \{\n\s*initObserver\(\)\n\s*\}, 100\)', '', content, flags=re.DOTALL)
content = re.sub(r'onUnmounted\(\(\) => \{[^}]+?observer[^}]+?\}\)', '', content, flags=re.DOTALL)

# 6. Replace CSS
css_search = r'/\* Cards container \*/.*?/\* Card header \*/'
new_css = """/* Cards container */
.cards-container {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 24px;
  padding: 0 40px;
}

/* Project card */
.project-card {
  position: relative;
  width: 280px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  padding: 14px;
  cursor: pointer;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.4);
  transition: transform 0.2s ease, border-color 0.2s ease;
}

.project-card:hover {
  transform: translateY(-4px);
  border-color: var(--text-primary);
  z-index: 10;
}

.delete-project-btn {
  position: absolute;
  top: -12px;
  right: -12px;
  width: 28px;
  height: 28px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: 50%;
  cursor: pointer;
  opacity: 0;
  transition: all 0.2s;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

.project-card:hover .delete-project-btn {
  opacity: 1;
}

.delete-project-btn:hover {
  color: var(--error-color, #dc3545);
  border-color: var(--error-color, #dc3545);
  transform: scale(1.1);
}

/* Card header */"""

content = re.sub(css_search, new_css, content, flags=re.DOTALL)

# Strip out unused hover stuff
content = re.sub(r'/\* Bottom decoration line \*/.*?/\* Empty state \*/', '/* Empty state */', content, flags=re.DOTALL)

with open('src/components/HistoryDatabase.vue', 'w') as f:
    f.write(content)
