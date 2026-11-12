import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc';fm.fontManager.addfont(FONT);plt.rcParams['font.family']=fm.FontProperties(fname=FONT).get_name()
D='#24334d';G='#2f5d46';M='#5b8c6f';L='#a8c6b4';X='#8a94a6'
fig,ax=plt.subplots(figsize=(11,4.4),dpi=160);fig.patch.set_facecolor('#fbfcfa')
names=['作者随笔','编辑部页面'];vals=[35,11];cols=[G,'#b9c3cf'];y=[0,1];ax.barh(y,vals,color=cols,height=.5)
ax.set_yticks(y);ax.set_yticklabels(names,fontsize=12,color=D);ax.invert_yaxis();ax.set_xlim(0,42)
for i,v in enumerate(vals):ax.text(v+0.8,i,str(v),va='center',fontsize=13,color=D,fontweight='bold')
for s in ['top','right','left']:ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#c9d5cd');ax.tick_params(axis='x',labelsize=9,colors=X);ax.tick_params(axis='y',length=0);ax.grid(axis='x',color='#dde5df',linewidth=.7);ax.set_axisbelow(True)
ax.set_title('副刊层复核：46 条 essay 的真实构成',fontsize=18,color=D,fontweight='bold',loc='left',pad=16)
ax.text(0,1.02,'35 篇作者随笔 + 11 个编辑部页面；短页面不再按“偏薄随笔”扩写',transform=ax.transAxes,fontsize=9.3,color=X)
fig.text(.012,.012,'复核日期 2026-11-12  ·  作者随笔最短 3,838 字符  ·  0 篇模板残留  ·  280 的“Son of a Biscuit et al.”为明示戏仿',fontsize=8,color=X)
plt.subplots_adjust(left=.18,right=.96,top=.86,bottom=.18)
fig.savefig('rubbish/review-pack/batch-17-essays.png',facecolor=fig.get_facecolor());plt.close(fig)
print('done')
