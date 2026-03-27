import re

file_path = 'frontend/src/components/Step4Report.vue'

with open(file_path, 'r') as f:
    text = f.read()

# Replace light pastel Gradients with single dark backgrounds for tool badges and headers:
# Purple
text = text.replace('background: linear-gradient(135deg, #F5F3FF 0%, #EDE9FE 100%);', 'background: rgba(109, 40, 217, 0.2);')
text = text.replace('color: #6D28D9;', 'color: #C4B5FD;') # Dark text to light purple
text = text.replace('color: #7C3AED;', 'color: #A78BFA;')
text = text.replace('border-color: #C4B5FD;', 'border-color: #5B21B6;')
text = text.replace('border: 1px solid #C4B5FD;', 'border: 1px solid #5B21B6;')
text = text.replace('color: #5B21B6;', 'color: #A78BFA;')
text = text.replace('color: #8B5CF6;', 'color: #C4B5FD;')

# Blue
text = text.replace('background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);', 'background: rgba(29, 78, 216, 0.2);')
text = text.replace('color: #1D4ED8;', 'color: #93C5FD;')
text = text.replace('color: #2563EB;', 'color: #60A5FA;')
text = text.replace('border-color: #93C5FD;', 'border-color: #1E40AF;')
text = text.replace('border: 1px solid #93C5FD;', 'border: 1px solid #1E40AF;')
text = text.replace('color: #1E40AF;', 'color: #93C5FD;')
text = text.replace('color: #60A5FA;', 'color: #DBEAFE;')


# Green
text = text.replace('background: linear-gradient(135deg, #F0FDF4 0%, #DCFCE7 100%);', 'background: rgba(21, 128, 61, 0.2);')
text = text.replace('color: #15803D;', 'color: #86EFAC;')
text = text.replace('border-color: #86EFAC;', 'border-color: #14532D;')

# Orange
text = text.replace('background: linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 100%);', 'background: rgba(194, 65, 12, 0.2);')
text = text.replace('color: #C2410C;', 'color: #FDBA74;')
text = text.replace('color: #EA580C;', 'color: #FB923C;')
text = text.replace('color: #9A3412;', 'color: #FDBA74;')
text = text.replace('color: #FB923C;', 'color: #FED7AA;')
text = text.replace('border-color: #FDBA74;', 'border-color: #7C2D12;')
text = text.replace('border: 1px solid #FDBA74;', 'border: 1px solid #7C2D12;')


# Cyan
text = text.replace('background: linear-gradient(135deg, #ECFEFF 0%, #CFFAFE 100%);', 'background: rgba(14, 116, 144, 0.2);')
text = text.replace('color: #0E7490;', 'color: #67E8F9;')
text = text.replace('border-color: #67E8F9;', 'border-color: #164E63;')

# Pink
text = text.replace('background: linear-gradient(135deg, #FDF2F8 0%, #FCE7F3 100%);', 'background: rgba(190, 24, 93, 0.2);')
text = text.replace('color: #BE185D;', 'color: #F9A8D4;')
text = text.replace('border-color: #F9A8D4;', 'border-color: #831843;')

# Gray (General tab / default)
text = text.replace('background: linear-gradient(135deg, #F9FAFB 0%, #F3F4F6 100%);', 'background: var(--bg-tertiary);')
text = text.replace('background: linear-gradient(135deg, #EEF2FF 0%, #E0E7FF 100%);', 'background: var(--bg-tertiary);')

# Agent tab active specific
text = text.replace('color: #4338CA;', 'color: #A5B4FC;')
text = text.replace('border-color: #A5B4FC;', 'border-color: #3730A3;')

with open(file_path, 'w') as f:
    f.write(text)
