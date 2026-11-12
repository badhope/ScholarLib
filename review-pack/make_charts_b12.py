# -*- coding: utf-8 -*-
import csv, statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch, Patch
import numpy as np
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
fm.fontManager.addfont(FONT)
plt.rcParams['font.family']=fm.FontProperties(fname=FONT).get_name()
plt.rcParams['axes.unicode_minus']=False
DARK='#24334d'; GREEN='#2f5d46'; MID='#5b8c6f'; LIGHT='#a8c6b4'; PALE='#e8f0eb'; GREY='#8a94a6'
rows=[r for r in csv.DictReader(open('/tmp/batch12_scores.csv',encoding='utf-8-sig')) if r['score']]
for r in rows: r['score']=float(r['score'])
rows.sort(key=lambda r:r['score'])
fig,ax=plt.subplots(figsize=(14,17.5),dpi=160)
fig.patch.set_facecolor('#fbfcfa')
labels=[f"{r['id']}  {r['title'][:20]}{'…' if len(r['title'])>20 else ''}" for r in rows]
vals=[r['score'] for r in rows]
colors=[GREEN if r['score']>=80 else (MID if r['score']>=70 else (LIGHT if r['score']>=60 else '#d3dfd6')) for r in rows]
y=np.arange(len(rows))
bars=ax.barh(y,vals,color=colors,height=0.66,edgecolor='none')
ax.set_yticks(y); ax.set_yticklabels(labels,fontsize=7.1,color=DARK)
ax.invert_yaxis(); ax.set_xlim(0,95); ax.set_ylim(-0.8,len(rows)-0.2)
for i,(b,v) in enumerate(zip(bars,vals)):
    ax.text(v+0.6,i,f'{v:.1f}',va='center',fontsize=6.9,color=DARK,fontweight='bold')
ax.grid(axis='x',color='#dde5df',linewidth=0.7,alpha=.8); ax.set_axisbelow(True)
for s in ['top','right','left']: ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#c9d5cd')
ax.tick_params(axis='x',labelsize=8,colors=GREY); ax.tick_params(axis='y',length=0)
ax.set_xlabel('五维合计（分）',fontsize=9,color=GREY)
ax.set_title('Rubbish 第 12 批人工审读：24–99 计分 70 篇',fontsize=18,color=DARK,fontweight='bold',pad=18,loc='left')
ax.text(0,1.012,'按 v5 两套五维尺逐篇人工通读；绿色 Q1（≥80）· 中绿 Q2（70–79）· 浅绿 Q3（60–69）· 灰绿 Q4（50–59）',
        transform=ax.transAxes,fontsize=9.5,color=GREY)
ax.legend(handles=[Patch(color=GREEN,label='Q1 一区'),Patch(color=MID,label='Q2 二区'),Patch(color=LIGHT,label='Q3 三区'),Patch(color='#d3dfd6',label='Q4 四区')],
          loc='lower right',frameon=False,fontsize=8.5,ncol=4,bbox_to_anchor=(1.0,-0.075))
fig.text(0.012,0.010,'另 5 篇为随笔（35、76、84、86、96），不评级、不占分区，未绘入本图。  ·  2026-11-12',
         fontsize=8,color=GREY)
plt.subplots_adjust(left=0.285,right=0.965,top=0.95,bottom=0.060)
fig.savefig('rubbish/review-pack/manual-review-24-99.png',facecolor=fig.get_facecolor())
plt.close(fig)
# overview
grades=[('Q1 一区',47,GREEN),('Q2 二区',150,MID),('Q3 三区',38,LIGHT),('Q4 四区',2,'#d3dfd6'),('NA 补全',2,'#c9d1dc'),('随笔不评级',35,'#b9c3cf')]
fig=plt.figure(figsize=(15,9.6),dpi=160); fig.patch.set_facecolor('#fbfcfa')
axh=fig.add_axes([0,0.885,1,0.115]); axh.axis('off')
axh.add_patch(FancyBboxPatch((0,0),1,1,transform=axh.transAxes,facecolor=DARK,edgecolor='none',boxstyle='square,pad=0'))
axh.text(0.045,0.60,'RUBBISH 主编站点总览',fontsize=25,color='white',fontweight='bold',va='center')
axh.text(0.045,0.27,'2026-11-12  ·  第 12 批（24–99）落库后  ·  全部人工通读口径',fontsize=10.5,color='#c9d5cd',va='center')
axh.text(0.965,0.50,'274 篇  /  271 已审读',fontsize=12,color='#e8f0eb',ha='right',va='center')
kpis=[('全站稿件','274','paper 239 · essay 35'),('已人工审读','271','覆盖率 98.9%'),('已计分','237','Q1 47 · Q2 150 · Q3 38 · Q4 2'),('随笔不评级','35','essay 不套论文尺')]
for i,(k,v,s) in enumerate(kpis):
    ax=fig.add_axes([0.055+i*0.232,0.745,0.215,0.115]); ax.axis('off')
    ax.add_patch(FancyBboxPatch((0,0),1,1,transform=ax.transAxes,facecolor='white',edgecolor='#dfe8e1',linewidth=1,boxstyle='round,pad=0.02,rounding_size=0.04'))
    ax.text(0.08,0.72,k,fontsize=11,color=GREY,va='center')
    ax.text(0.08,0.36,v,fontsize=30,color=DARK,fontweight='bold',va='center')
    ax.text(0.08,0.12,s,fontsize=8.8,color=GREEN,va='center')
ax1=fig.add_axes([0.055,0.095,0.60,0.56])
names=[g[0] for g in grades][::-1]; counts=[g[1] for g in grades][::-1]; cols=[g[2] for g in grades][::-1]
y=np.arange(len(names)); ax1.barh(y,counts,color=cols,height=0.62)
ax1.set_yticks(y); ax1.set_yticklabels(names,fontsize=10,color=DARK); ax1.set_xlim(0,165)
ax1.grid(axis='x',color='#e3ebe6',linewidth=.8); ax1.set_axisbelow(True)
for s in ['top','right','left']: ax1.spines[s].set_visible(False)
ax1.tick_params(axis='x',labelsize=9,colors=GREY); ax1.tick_params(axis='y',length=0)
for i,v in enumerate(counts): ax1.text(v+1.8,i,str(v),va='center',fontsize=9.5,color=DARK,fontweight='bold')
ax1.set_title('全站年级分布（篇）',fontsize=13,color=DARK,fontweight='bold',loc='left',pad=30)
ax1.text(0,1.055,'Q1/Q2/Q3/Q4 为 v5 两段式；NA 为不完整稿已经编辑部补全；随笔单独计数',
         transform=ax1.transAxes,fontsize=8.2,color=GREY)
ax2=fig.add_axes([0.695,0.095,0.27,0.56]); ax2.axis('off')
ax2.add_patch(FancyBboxPatch((0,0),1,1,transform=ax2.transAxes,facecolor='white',edgecolor='#dfe8e1',linewidth=1,boxstyle='round,pad=0.02,rounding_size=0.04'))
ax2.text(0.08,0.94,'第 12 批构成',fontsize=13,color=DARK,fontweight='bold',va='top')
ax2.text(0.08,0.84,'24–99 · 75 篇（缺 98）',fontsize=9,color=GREY,va='top')
items=[('Q1 一区',8,GREEN),('Q2 二区',38,MID),('Q3 三区',22,LIGHT),('Q4 四区',2,'#d3dfd6'),('随笔不评级',5,'#b9c3cf')]
yy=0.70
for k,v,c in items:
    ax2.add_patch(FancyBboxPatch((0.08,yy-0.015),0.84,0.10,transform=ax2.transAxes,facecolor=PALE,edgecolor='none',boxstyle='round,pad=0.0,rounding_size=0.01'))
    ax2.add_patch(FancyBboxPatch((0.08,yy-0.015),0.84*(v/75),0.10,transform=ax2.transAxes,facecolor=c,edgecolor='none',boxstyle='round,pad=0.0,rounding_size=0.01'))
    ax2.text(0.10,yy+0.035,f'{k}',fontsize=9.5,color='white' if v>=20 else DARK,va='center')
    ax2.text(0.90,yy+0.035,f'{v}',fontsize=9.5,color=DARK,va='center',ha='right',fontweight='bold')
    yy-=0.125
ax2.text(0.08,0.10,'均分 71.5  ·  中位 70.1  ·  最高 86.0  ·  最低 55.0',fontsize=8.8,color=GREY,va='bottom')
ax2.text(0.08,0.035,'计分 70 篇，另复核 15 篇历史问题稿',fontsize=8.2,color=GREEN,va='bottom')
strip=fig.add_axes([0.055,0.005,0.91,0.045]); strip.axis('off')
strip.add_patch(FancyBboxPatch((0,0),1,1,transform=strip.transAxes,facecolor=DARK,edgecolor='none',boxstyle='square,pad=0'))
strip.text(0.02,0.5,'站点侧样本：近 3 日访问 154 次（page_views 仅保留近 3 日，样本不足，不作趋势结论）    ·    注册用户 52    ·    投稿 277    ·    评论 7    ·    论坛主题 10 / 回复 8',
           fontsize=8.8,color='#e8f0eb',va='center')
fig.savefig('rubbish/review-pack/site-overview-2026-11-12-b12.png',facecolor=fig.get_facecolor())
plt.close(fig)
print('done')
