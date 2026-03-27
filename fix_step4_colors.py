import re

file_path = 'frontend/src/components/Step4Report.vue'

with open(file_path, 'r') as f:
    content = f.read()

# Replace Text colors
content = re.sub(r'color:\s*#(111827|1F2937);?', r'color: var(--text-primary);', content, flags=re.IGNORECASE)
content = re.sub(r'color:\s*#(374151|4B5563);?', r'color: var(--text-secondary);', content, flags=re.IGNORECASE)
content = re.sub(r'color:\s*#(6B7280|9CA3AF|64748B);?', r'color: var(--text-muted);', content, flags=re.IGNORECASE)

# Replace Borders
content = re.sub(r'border-color:\s*#(E5E7EB|F3F4F6|D1D5DB);?', r'border-color: var(--border-color);', content, flags=re.IGNORECASE)
content = re.sub(r'border:\s*(\d+px [a-z]+) #(E5E7EB|F3F4F6|D1D5DB);?', r'border: \1 var(--border-color);', content, flags=re.IGNORECASE)
content = re.sub(r'border-([^:]+):\s*(\d+px [a-z]+) #(E5E7EB|F3F4F6|D1D5DB);?', r'border-\1: \2 var(--border-color);', content, flags=re.IGNORECASE)
content = re.sub(r'stroke:\s*#(E5E7EB|F3F4F6|D1D5DB|4B5563);?', r'stroke: var(--border-color);', content, flags=re.IGNORECASE)


# Replace Backgrounds
content = re.sub(r'background(-color)?:\s*#FFFFFF;?', r'background: var(--bg-primary);', content, flags=re.IGNORECASE)
content = re.sub(r'background(-color)?:\s*#(F9FAFB|F3F4F6|E5E7EB);?', r'background: var(--bg-secondary);', content, flags=re.IGNORECASE)

with open(file_path, 'w') as f:
    f.write(content)
