import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# 1. Load your dataset
try:
    df = pd.read_csv('final_corpus - Corpus.csv')
except FileNotFoundError:
    print("Error: Ensure 'data_annotation.csv' is in the same folder as this script.")
    exit()

# Set standard academic styling
plt.style.use('ggplot') 

# --- 1. HEATMAP (Selection Logic vs. Annotator Type) ---
plt.figure(figsize=(10, 7))
logic_type_cross = pd.crosstab(df['Annotator Type'], df['Annotator Selection Logic'])
sns.heatmap(logic_type_cross, annot=True, cmap="Blues", fmt='d')
plt.title('Annotator Type vs. Selection Logic')
plt.tight_layout()
plt.savefig('heatmap_logic_mismatch.png')
plt.close()

# --- 2. STACKED BAR (Geographic Distribution) ---
# This visualizes Geographic Hegemony [cite: 615]
geo_config = pd.crosstab(df['Geographic Focus'], df['Annotation Configuration'], normalize='index')
ax = geo_config.plot(kind='bar', stacked=True, figsize=(10, 6), color=['#4E79A7', '#F28E2B', '#E15759', '#76B7B2'])
plt.title('Annotation Configuration by Geography')
plt.ylabel('Proportion')
plt.xticks(rotation=0)
plt.legend(title='Configuration', bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig('stacked_geo_distribution.png')
plt.close()

# --- 3. RADAR CHART (Configuration Profiles) ---
# Mapping the "Epistemic Profiles" of different workflows [cite: 915, 925]
categories = list(df['Annotator Selection Logic'].unique())
N = len(categories)
angles = [n / float(N) * 2 * np.pi for n in range(N)]
angles += angles[:1]

fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
for config in df['Annotation Configuration'].unique():
    subset = df[df['Annotation Configuration'] == config]
    values = subset['Annotator Selection Logic'].value_counts(normalize=True).reindex(categories, fill_value=0).tolist()
    values += values[:1]
    ax.plot(angles, values, linewidth=2, label=config)
    ax.fill(angles, values, alpha=0.1)

plt.xticks(angles[:-1], categories)
plt.title('Epistemic Logic Profiles per Configuration', y=1.1)
plt.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
plt.savefig('radar_paradigm_profiles.png')
plt.close()

# --- 4. PIE CHART (Labor Composition) ---
# Visualizes the dominance of "Crowd" labor over "Situated Knowers" [cite: 72, 885]
plt.figure(figsize=(8, 8))
df['Annotator Type'].value_counts().plot.pie(autopct='%1.1f%%', startangle=140, colors=sns.color_palette('pastel'))
plt.title('Composition of Annotator Types')
plt.ylabel('') 
plt.tight_layout()
plt.savefig('pie_labor_composition.png')
plt.close()

print("All 4 visualizations generated: heatmap_logic_mismatch.png, stacked_geo_distribution.png, radar_paradigm_profiles.png, pie_labor_composition.png")