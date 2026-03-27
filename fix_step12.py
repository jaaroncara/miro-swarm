import re
import os

files = [
    'frontend/src/components/Step2EnvSetup.vue',
    'frontend/src/components/Step1GraphBuild.vue'
]

for file_path in files:
    if not os.path.exists(file_path):
        continue
    with open(file_path, 'r') as f:
        content = f.read()

    # Generic Backgrounds
    content = re.sub(r'background(-color)?:\s*#(F1F5F9|E2E8F0|CBD5E1|E5E5E5|F0F0F0|EEF2F6|EEF2FF|E3F2FD|F5F5F5|FAFAFA|FFFFFF|FFF);?', r'background\1: var(--bg-secondary);', content, flags=re.IGNORECASE)
    content = re.sub(r'background(-color)?:\s*#(E0E0E0|EAEAEA|DDD|CCC);?', r'background\1: var(--bg-tertiary);', content, flags=re.IGNORECASE)
    
    # Generic Texts
    content = re.sub(r'color:\s*#(000000|000|222|333|444|1E293B|334155|475569);?', r'color: var(--text-primary);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(666|777|888|999|AAA|BBB|CCC|94A3B8);?', r'color: var(--text-secondary);', content, flags=re.IGNORECASE)
    
    # Generic Borders
    content = re.sub(r'border(-color|-bottom|-top|-left|-right)?:\s*([a-z0-9\s]+)?#(E5E5E5|DDD|CCC|EAEAEA|E0E0E0|F1F5F9|E2E8F0|CBD5E1|AAA);?', r'border\1: \2var(--border-color);', content, flags=re.IGNORECASE)
    content = re.sub(r'stroke="#(000000|000|222|333|444|1E293B|334155|475569)"', r'stroke="var(--text-primary)"', content, flags=re.IGNORECASE)
    content = re.sub(r'stroke="#(E5E5E5|DDD|CCC|EAEAEA|E0E0E0|F1F5F9)"', r'stroke="var(--border-color)"', content, flags=re.IGNORECASE)

    # Some pastel background statuses -> RGBA equivalents for dark mode
    # Green status
    content = re.sub(r'background(-color)?:\s*#(E8F5E9|DCFCE7);?', r'background\1: rgba(34, 197, 94, 0.1);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(2E7D32|16A34A|047857);?', r'color: #4ADE80;', content, flags=re.IGNORECASE)
    # Red status
    content = re.sub(r'background(-color)?:\s*#(FEE2E2);?', r'background\1: rgba(239, 68, 68, 0.1);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(DC2626|B91C1C);?', r'color: #F87171;', content, flags=re.IGNORECASE)
    # Yellow status
    content = re.sub(r'background(-color)?:\s*#(FEF3C7);?', r'background\1: rgba(245, 158, 11, 0.1);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(D97706|B45309);?', r'color: #FBBF24;', content, flags=re.IGNORECASE)
    # Orange / Primary action
    content = re.sub(r'background(-color)?:\s*#(FFCCBC);?', r'background\1: rgba(255, 87, 34, 0.1);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(FF5722);?', r'color: #FF8A65;', content, flags=re.IGNORECASE)
    content = re.sub(r'background(-color)?:\s*#(FF5722);?', r'background\1: #FF5722;', content, flags=re.IGNORECASE)  # For buttons, #FF5722 is probably ok in dark mode.
    
    # Blue statuses
    content = re.sub(r'background(-color)?:\s*#(BBDEFB|E3F2FD);?', r'background\1: rgba(59, 130, 246, 0.1);', content, flags=re.IGNORECASE)
    content = re.sub(r'color:\s*#(0D47A1|1565C0|1D4ED8);?', r'color: #60A5FA;', content, flags=re.IGNORECASE)

    # Indigo actions
    content = re.sub(r'color:\s*#6366F1;?', r'color: #818CF8;', content, flags=re.IGNORECASE)
    content = re.sub(r'background(-color)?:\s*#818CF8;?', r'background\1: #6366F1;', content, flags=re.IGNORECASE)
    
    # Text shadow/box shadow fixes (generic)
    content = r"""{}""".format(content)

    with open(file_path, 'w') as f:
        f.write(content)
