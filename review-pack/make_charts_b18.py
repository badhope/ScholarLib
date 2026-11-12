import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc';fm.fontManager.addfont(FONT);plt.rcParams['font.family']=fm.FontProperties(fname=FONT).get_name()
D='#24334d';G='#2f5d46';M='#5b8c6f';X='#8a94a6'
fig,ax=plt.subplots(figsize=(11,4.4),dpi=160);fig.patch.set_facecolor('#fbfcfa')
names=['保留 Q1','降 Q2'];vals=[10,1];ax.barh([0,1],vals,color=[G,'#b9c3cf'],height=.5);ax.set_yticks([0,1]);ax.set_yticklabels(names,fontsize=12,color=D);ax.invert_yaxis();ax.set_xlim(0,12)
for i,v in enumerate(vals):ax.text(v+.3,i,str(v),va='center',fontsize=13,color=D,fontweight='bold')
for s in ['top','right','left']:ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#c9d5cd');ax.tick_params(axis='x',labelsize=9,colors=X);ax.tick_params(axis='y',length=0);ax.grid(axis='x',color='#dde5df',linewidth=.7);ax.set_axisbelow(True)
ax.set_title('Q1 补偿稿终审：11 篇',fontsize=18,color=D,fontweight='bold',loc='left',pad=16)
ax.text(0,1.02,'10 篇保留、205 执行 68 低于底线降 Q2；Q1 由 44 变 43',transform=ax.transAxes,fontsize=9.3,color=X)
fig.text(.012,.012,'复核日期 2026-11-12  ·  逐篇核对五维、判词与证据  ·  不再挂“待复核”',fontsize=8,color=X)
plt.subplots_adjust(left=.18,right=.96,top=.86,bottom=.18)
fig.savefig('rubbish/review-pack/batch-18-q1-compensation.png',facecolor=fig.get_facecolor());plt.close(fig)
print('done')
