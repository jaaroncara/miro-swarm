import re
import os

files = [
    'frontend/src/components/Step5Interaction.vue',
    'frontend/src/components/Step4Report.vue',
    'frontend/src/components/Step3Simulation.vue',
    'frontend/src/components/Step2EnvSetup.vue',
    'frontend/src/components/Step1GraphBuild.vue'
]

for file_path in files:
    if not os.path.exists(file_path):
        continue
    with open(file_path, 'r') as f:
        content = f.read()

    # Colors
    content = re.sub(r'color:\s*#(1F2937|111827);?', r'color: var(--text-primary);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(374151|4B5563);?', r'color: var(--text-secondary);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(64748B|6B7280|9CA3AF|D1D5DB|E5E7EB);?', r'color: var(--text-muted);', content, flags=re.IGNORECASE)

    # Backgrounds
    content = re.sub(r'background:\s*#(FFFFFF|F8F9FA|FFF);?', r'background: var(--bg-primary);', content, flags=re.IGNORECASE)
    content = re.sub(r'background(-color)?:\s*#(F8FAFC|F3F4F6|E5E7EB|F9FAFB);?', r'background: var(--bg-secondary);', content, flags=re.IGNORECASE)
    content = re.sub(r'background(-color)?:\s*#(F5F5F5|FAFAFA|F9F9F9);?', r'background: var(--bg-secondary);', content, flags=re.IGNORECASE)
    content = re.sub(r'background:\s*#(1F2937|D1D5DB);?', r'background: var(--bg-tertiary);', content, flags=re.IGNORECASE)
    content = re.sub(r'background(-color)?:\s*#000000;?', r'background: var(--bg-tertiary);', content, flags=re.IGNORECASE)
    
    # Borders
    content = re.sub(r'border(-color)?:\s*(1px solid )?#(D1D5DB|E5E7EB|F3F4F6|EEE|EAEAEA);?', r'border\1: \2var(--border-color);', content, flags=re.IGNORECASE)
    content = re.sub(r'stroke:\s*#(E5E7EB|F3F4F6|D1D5DB|4B5563);?', r'stroke: var(--border-color);', content, flags=re.IGNORECASE)

    with open(file_path, 'w') as f:
        f.write(content)
