import re
import os

files = [
    'frontend/src/components/Step5Interaction.vue',
    'frontend/src/components/Step3Simulation.vue',
    'frontend/src/components/Step2EnvSetup.vue',
    'frontend/src/components/Step1GraphBuild.vue'
]

for file_path in files:
    if not os.path.exists(file_path):
        continue
    with open(file_path, 'r') as f:
        content = f.read()

    # Generic backgrounds and strokes
    content = re.sub(r'border(-[a-z]+)?:\s*([0-9]+px solid )?#(E5E7EB|F3F4F6|D1D5DB|1F2937|374151);?', r'border\1: \2var(--border-color);', content, flags=re.IGNORECASE)
    content = re.sub(r'stroke="#(E5E7EB|D1DDB|F3F4F6|D1D5DB)"', r'stroke="var(--border-color)"', content, flags=re.IGNORECASE)
    content = re.sub(r'stroke="#(4B5563|374151|6B7280)"', r'stroke="var(--text-secondary)"', content, flags=re.IGNORECASE)
    
    # Gradients
    content = re.sub(r'background:\s*linear-gradient\([^)]+#FFFFFF[^)]+#FAFBFC[^)]*\);?', r'background: var(--bg-tertiary);', content, flags=re.IGNORECASE)
    content = re.sub(r'background:\s*linear-gradient\([^)]+#F8FAFC[^)]+#F1F5F9[^)]*\);?', r'background: var(--bg-tertiary);', content, flags=re.IGNORECASE)
    content = re.sub(r'background:\s*linear-gradient\([^)]+#1F2937[^)]+#374151[^)]*\);?', r'background: var(--bg-secondary);', content, flags=re.IGNORECASE)
    
    # Specific colors
    content = re.sub(r'color:\s*#(FFFFFF|FFF);?', 'color: var(--text-primary);', content, flags=re.IGNORECASE)
    content = re.sub(r'border-top-color:\s*#(FFFFFF|FFF);?', 'border-top-color: var(--text-primary);', content, flags=re.IGNORECASE)
    
    # Background flat colors
    content = re.sub(r'background:\s*#(9CA3AF|374151|1F2937);?', r'background: var(--bg-secondary);', content, flags=re.IGNORECASE)
    
    # Pastels badge colors
    content = re.sub(r'background:\s*#(ECFDF5|D1FAE5|F0FDF4);?', r'background: rgba(16, 185, 129, 0.1);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(047857|065F46);?', r'color: #34D399;', content, flags=re.IGNORECASE)
    content = re.sub(r'border-color:\s*#(10B981);?', r'border-color: #34D399;', content, flags=re.IGNORECASE)
    content = re.sub(r'background:\s*#(10B981);?', r'background: #34D399;', content, flags=re.IGNORECASE)
    
    content = re.sub(r'color:\s*#8B5CF6;?', r'color: #A78BFA;', content, flags=re.IGNORECASE) # purple
    content = re.sub(r'color:\s*#3B82F6;?', r'color: #60A5FA;', content, flags=re.IGNORECASE) # blue
    content = re.sub(r'color:\s*#F97316;?', r'color: #FB923C;', content, flags=re.IGNORECASE) # orange
    content = re.sub(r'color:\s*#22C55E;?', r'color: #4ADE80;', content, flags=re.IGNORECASE) # green


    with open(file_path, 'w') as f:
        f.write(content)

