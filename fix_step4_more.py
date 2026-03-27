import re

file_path = 'frontend/src/components/Step4Report.vue'

with open(file_path, 'r') as f:
    content = f.read()

# Additional Grays in Step4Report.vue that need dark theme variables
content = re.sub(r'color:\s*#(1F2937|111827);?', r'color: var(--text-primary);', content, flags=re.IGNORECASE)
content = re.sub(r'color:\s*#(374151|4B5563);?', r'color: var(--text-secondary);', content, flags=re.IGNORECASE)
content = re.sub(r'color:\s*#(64748B);?', r'color: var(--text-muted);', content, flags=re.IGNORECASE)

content = re.sub(r'background:\s*#(F8F9FA);?', r'background: var(--bg-primary);', content, flags=re.IGNORECASE)
content = re.sub(r'background(-color)?:\s*#(F8FAFC|F3F4F6|E5E7EB|F9FAFB);?', r'background: var(--bg-secondary);', content, flags=re.IGNORECASE)
content = re.sub(r'background:\s*#(1F2937|D1D5DB);?', r'background: var(--bg-tertiary);', content, flags=re.IGNORECASE)

# Some of these are light background colors for tags / pills. In a dark mode, we might want a darker variant
# like dark purple or dark cyan instead of bright pastel. 
# But we can start by just fixing the plain white/black backgrounds
content = re.sub(r'background(-color)?:\s*#000000;?', r'background: var(--bg-tertiary);', content, flags=re.IGNORECASE)
content = re.sub(r'border(-color)?:\s*(1px solid )?#(D1D5DB|E5E7EB|F3F4F6);?', r'border\1: \2var(--border-color);', content, flags=re.IGNORECASE)


with open(file_path, 'w') as f:
    f.write(content)
