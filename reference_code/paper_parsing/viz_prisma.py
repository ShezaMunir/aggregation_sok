import matplotlib.pyplot as plt
import matplotlib.patches as patches

def draw_prisma():
    fig, ax = plt.subplots(figsize=(10, 12))
    
    # Define box properties for an academic look
    box_style = dict(boxstyle='round,pad=0.5', facecolor='#f9f9f9', edgecolor='black', linewidth=1)
    exclude_style = dict(boxstyle='round,pad=0.5', facecolor='#fff0f0', edgecolor='red', linewidth=1)
    
    # 1. Identification
    ax.text(0.5, 0.95, "Identification:\nACM Digital Library Search", 
            ha='center', va='center', bbox=box_style, fontsize=11)
    
    # 2. Keyword Filtration
    ax.text(0.5, 0.82, "Keyword Filtration:\nApplied Tier 1, 2, & 3 Schema", 
            ha='center', va='center', bbox=box_style, fontsize=11)
    
    # 3. Screening (606)
    ax.text(0.5, 0.65, "Screening Phase:\nTitle/Abstract Screening\n(n = 606)", 
            ha='center', va='center', bbox=box_style, fontsize=11)
    
    # 3b. Excluded (Screening)
    ax.text(0.85, 0.65, "Excluded:\n(n = 461)", 
            ha='center', va='center', bbox=exclude_style, fontsize=10)
    
    # 4. Full Text Review (145)
    ax.text(0.5, 0.45, "Eligibility Phase:\nFull-Text Review\n(n = 145)", 
            ha='center', va='center', bbox=box_style, fontsize=11)
    
    # 4b. Excluded (Full Text)
    ax.text(0.85, 0.45, "Excluded:\n(n = TBD)", 
            ha='center', va='center', bbox=exclude_style, fontsize=10)
    
    # 5. Final Inclusion
    ax.text(0.5, 0.25, "Final Included Corpus:\nData Extraction Phase\n(In Progress)", 
            ha='center', va='center', bbox=box_style, fontweight='bold', fontsize=11)

    # Drawing Arrows
    arrow_props = dict(arrowstyle='<-', color='black', lw=1.5)
    ax.annotate('', xy=(0.5, 0.90), xytext=(0.5, 0.87), arrowprops=arrow_props)
    ax.annotate('', xy=(0.5, 0.77), xytext=(0.5, 0.70), arrowprops=arrow_props)
    ax.annotate('', xy=(0.5, 0.60), xytext=(0.5, 0.50), arrowprops=arrow_props)
    ax.annotate('', xy=(0.5, 0.40), xytext=(0.5, 0.30), arrowprops=arrow_props)
    
    # Side arrows for exclusions'
    arrow_props = dict(arrowstyle='->', color='black', lw=1.5)
    ax.annotate('', xy=(0.75, 0.65), xytext=(0.65, 0.65), arrowprops=arrow_props)
    ax.annotate('', xy=(0.75, 0.45), xytext=(0.65, 0.45), arrowprops=arrow_props)

    # Formatting the plot
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    plt.title("PRISMA Flow Diagram: Data Annotation SoK", fontsize=14, pad=20)
    
    # Save the figure for your paper
    plt.savefig('PRISMA_Diagram.png', dpi=300, bbox_inches='tight')
    plt.show()

if __name__ == "__main__":
    draw_prisma()