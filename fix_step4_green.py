import re

file_path = 'frontend/src/components/Step4Report.vue'

with open(file_path, 'r') as f:
    text = f.read()

# Fix light mode green components
text = text.replace('background: #ECFDF5;', 'background: rgba(16, 185, 129, 0.1);')
text = text.replace('background: #D1FAE5;', 'background: rgba(16, 185, 129, 0.15);')
text = text.replace('border-color: #A7F3D0;', 'border-color: rgba(16, 185, 129, 0.3);')
text = text.replace('border: 1px solid #A7F3D0;', 'border: 1px solid rgba(16, 185, 129, 0.3);')
text = text.replace('background: #A7F3D0;', 'background: rgba(16, 185, 129, 0.2);')
text = text.replace('color: #065F46;', 'color: #34D399;')
text = text.replace('color: #059669;', 'color: #10B981;')
text = text.replace('color: #10B981;', 'color: #34D399;')
text = text.replace('color: #15803D;', 'color: #34D399;')

# Blue
text = text.replace('background: #DBEAFE;', 'background: rgba(59, 130, 246, 0.1);')
text = text.replace('border-color: #93C5FD;', 'border-color: rgba(59, 130, 246, 0.3);')

# Purple & Indigo
text = text.replace('background: #EDE9FE;', 'background: rgba(139, 92, 246, 0.1);')
text = text.replace('background: #EEF2FF;', 'background: rgba(99, 102, 241, 0.1);')
text = text.replace('background: #E0E7FF;', 'background: rgba(99, 102, 241, 0.15);')

# Orange
text = text.replace('background: #FFEDD5;', 'background: rgba(249, 115, 22, 0.1);')

# Pink/Red
text = text.replace('background: #FDF2F8;', 'background: rgba(236, 72, 153, 0.1);')
text = text.replace('background: #FCE7F3;', 'background: rgba(236, 72, 153, 0.15);')

# Backgrounds
text = text.replace('background-color: var(--bg-primary);', 'background-color: transparent;') 
text = text.replace('background-color: var(--bg-secondary);', 'background: var(--bg-secondary);') 

with open(file_path, 'w') as f:
    f.write(text)
