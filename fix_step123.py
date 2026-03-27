import re
import os

files = [
    'frontend/src/components/Step3Simulation.vue',
    'frontend/src/components/Step2EnvSetup.vue',
    'frontend/src/components/Step1GraphBuild.vue'
]

for file_path in files:
    if not os.path.exists(file_path):
        continue
    with open(file_path, 'r') as f:
        content = f.read()

    # Borders
    content = re.sub(r'border(-[a-z]+)?:\s*([0-9a-z]+ solid )?#(DDD|CCC|EAEAEA|E0E0E0|BBB|333);?', r'border\1: \2var(--border-color);', content, flags=re.IGNORECASE)

    # Backgrounds
    content = re.sub(r'background(-color)?:\s*#(F5F5F5|F2FAF6|E0E0E0|EEE|222|333);?', r'background\1: var(--bg-secondary);', content, flags=re.IGNORECASE)
    
    # Colors
    content = re.sub(r'color:\s*#(000|000000|222|333|555);?', r'color: var(--text-primary);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(555555|777|999|BBB|CCC|DDD);?', r'color: var(--text-secondary);', content, flags=re.IGNORECASE)
    
    # Primary button stuff
    content = re.sub(r'background-color:\s*#1A936F;?', r'background-color: var(--accent-color, #1A936F);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#1A936F;?', r'color: var(--accent-color, #1A936F);', content, flags=re.IGNORECASE)
    content = re.sub(r'border-color:\s*#1A936F;?', r'border-color: var(--accent-color, #1A936F);', content, flags=re.IGNORECASE)
    
    with open(file_path, 'w') as f:
        f.write(content)