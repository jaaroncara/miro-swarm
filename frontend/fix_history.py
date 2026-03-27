import re

with open('src/components/HistoryDatabase.vue', 'r') as f:
    content = f.read()

# Remove tech-grid-bg
content = re.sub(r'<!-- Background decoration.*?</style>', lambda m: m.group().replace('<div v-if="projects.length > 0 || loading" class="tech-grid-bg">', '<!-- <div class="tech-grid-bg">'), content, flags=re.DOTALL)

