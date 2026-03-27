<template>
  <router-view />
</template>

<script setup>
// Uses Vue Router for page management
</script>

<style>
:root {
  /* High-Contrast Dark Theme Variables */
  --bg-primary: #121212;
  --bg-secondary: #1E1E1E;
  --bg-tertiary: #2D2D2D;
  --bg-scrollbar-track: #1A1A1A;
  
  --text-primary: #FFFFFF;
  --text-secondary: #B0B0B0;
  --text-muted: #808080;
  
  --border-color: #333333;
  --border-hover: #555555;
  
  --accent-color: #4A90E2;    /* Kept some blue for accent where needed */
  --accent-hover: #357ABD;
  
  /* Status Colors */
  --success-color: #28a745;
  --error-color: #dc3545;
  --warning-color: #ffc107;
  --info-color: #17a2b8;
}

/* Global style reset */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--text-primary);
  background-color: var(--bg-primary);
}

/* Scrollbar styles */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--bg-scrollbar-track);
}

::-webkit-scrollbar-thumb {
  background: var(--border-color);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--border-hover);
}

/* Global button styles */
button {
  font-family: inherit;
}
</style>
