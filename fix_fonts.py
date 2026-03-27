import os
import re
import glob

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Replace 'Space Grotesk' with 'Inter'
    content = re.sub(r"'Space Grotesk'[^;]+", r"'Inter', system-ui, sans-serif", content)
    
    # Replace 'Times New Roman' with 'Inter'
    content = re.sub(r"'Times New Roman'[^;]+", r"'Inter', system-ui, sans-serif", content)

    with open(filepath, 'w') as f:
        f.write(content)

for root, _, files in os.walk('frontend/src'):
    for file in files:
        if file.endswith('.vue'):
            process_file(os.path.join(root, file))

