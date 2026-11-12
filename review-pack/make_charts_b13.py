# -*- coding: utf-8 -*-
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

# 1 audit composition
fig,ax=plt.subplots(figsize=(12,5.2),dpi=160); fig.patch.set_facecolor('#fbfcfa')
cats=['随笔/戏仿（不评级）','Q3 三区','Q2 二区','Q4 四区']
vals=[39,34,15,2]
cols=['#b9c3cf',LIGHT,MID,'#d3dfd6']
y=np.arange(len(cats))
bars=ax.barh(y,vals,color=cols,height=.58)
ax.set_yticks(y); ax.set_yticklabels(cats,fontsize=11,color=DARK)
ax.invert_yaxis(); ax.set_xlim(0,46)
for i,(b,v) in enumerate(zip(bars,vals)):
    ax.text(v+.7,i,str(v),va='center',fontsize=12,color=DARK,fontweight='bold')
for s in ['top','right','left']: ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#c9d5cd'); ax.tick_params(axis='x',labelsize=9,colors=GREY); ax.tick_params(axis='y',length=0)
ax.grid(axis='x',color='#dde5df',linewidth=.7,alpha=.8); ax.set_axisbelow(True)
ax.set_xlabel('篇次',fontsize=9,color=GREY)
ax.set_title('第 13 批历史稿复核：90 篇次构成',fontsize=18,color=DARK,fontweight='bold',loc='left',pad=16)
ax.text(0,1.02,'38 篇 Q3 + 2 篇 Q4 + 35 篇随笔 + 13 篇补全/争议稿 + 2 篇补全后重评；其中 31、53、60、71 转随笔，100、102 补评 Q2',transform=ax.transAxes,fontsize=9.3,color=GREY)
fig.text(.012,.012,'复核日期 2026-11-12  ·  全部逐篇核对生产正文与文体声明，PDF 抽检 10 篇',fontsize=8,color=GREY)
plt.subplots_adjust(left=.22,right=.96,top=.88,bottom=.16)
fig.savefig('rubbish/review-pack/batch-13-audit-90.png',facecolor=fig.get_facecolor()); plt.close(fig)

# 2 site overview
grades=[('Q1 一区',47,GREEN),('Q2 二区',152,MID),('Q3 三区',34,LIGHT),('Q4 四区',2,'#d3dfd6'),('随笔不评级',39,'#b9c3cf')]
fig=plt.figure(figsize=(15,9.6),dpi=160); fig.patch.set_facecolor('#fbfcfa')
axh=fig.add_axes([0,0.885,1,0.115]); axh.axis('off')
axh.add_patch(FancyBboxPatch((0,0),1,1,transform=axh.transAxes,facecolor=DARK,edgecolor='none',boxstyle='square,pad=0'))
axh.text(.045,.60,'RUBBISH 主编站点总览',fontsize=25,color='white',fontweight='bold',va='center')
axh.text(.045,.27,'2026-11-12  ·  第 13 批历史稿复核后  ·  全部人工通读口径',fontsize=10.5,color='#c9d5cd',va='center')
axh.text(.965,.50,'274 篇  /  274 已审读',fontsize=12,color='#e8f0eb',ha='right',va='center')
kpis=[('全站稿件','274','paper 235 · essay 39'),('已人工审读','274','覆盖率 100%'),('已计分','233','Q1 47 · Q2 152 · Q3 34 · Q4 2'),('随笔不评级','39','essay 不套论文尺')]
for i,(k,v,s) in enumerate(kpis):
    ax=fig.add_axes([.055+i*.232,.745,.215,.115]); ax.axis('off')
    ax.add_patch(FancyBboxPatch((0,0),1,1,transform=ax.transAxes,facecolor='white',edgecolor='#dfe8e1',linewidth=1,boxstyle='round,pad=0.02,rounding_size=0.04'))
    ax.text(.08,.72,k,fontsize=11,color=GREY,va='center')
    ax.text(.08,.36,v,fontsize=30,color=DARK,fontweight='bold',va='center')
    ax.text(.08,.12,s,fontsize=8.8,color=GREEN,va='center')
ax1=fig.add_axes([.055,.095,.60,.56])
names=[g[0] for g in grades][::-1]; counts=[g[1] for g in grades][::-1]; cols=[g[2] for g in grades][::-1]
y=np.arange(len(names)); ax1.barh(y,counts,color=cols,height=.62)
ax1.set_yticks(y); ax1.set_yticklabels(names,fontsize=11,color=DARK); ax1.set_xlim(0,170)
for i,v in enumerate(counts): ax1.text(v+2,i,str(v),va='center',fontsize=11,color=DARK,fontweight='bold')
for s in ['top','right','left']: ax1.spines[s].set_visible(False)
ax1.spines['bottom'].set_color('#c9d5cd'); ax1.tick_params(axis='x',labelsize=9,colors=GREY); ax1.tick_params(axis='y',length=0)
ax1.grid(axis='x',color='#dde5df',linewidth=.7,alpha=.8); ax1.set_axisbelow(True)
ax1.set_title('年级分布（篇）',fontsize=14,color=DARK,fontweight='bold',loc='left',pad=12)
ax2=fig.add_axes([.70,.095,.265,.56]); ax2.axis('off')
stats=[('注册用户','52'),('投稿','277'),('评论','7'),('论坛主题/回复','10 / 8'),('近 3 日访问','154')]
ax2.text(0,1.0,'站点侧样本',fontsize=14,color=DARK,fontweight='bold',va='top')
for i,(k,v) in enumerate(stats):
    yy=.86-i*.17
    ax2.text(0,yy,k,fontsize=10.5,color=GREY,va='center')
    ax2.text(.98,yy,v,fontsize=15,color=GREEN,fontweight='bold',va='center',ha='right')
ax2.text(0,.02,'page_views 仅保留 3 个自然日，样本不足，不作趋势结论。',fontsize=8,color=GREY,va='bottom')
fig.text(.012,.010,'第 13 批：90 篇次复核；31/53/60/71 转 essay；296/300/301 补 reviewed_at；44/57/99 正文级补全保持。',fontsize=8,color=GREY)
fig.savefig('rubbish/review-pack/site-overview-2026-11-12-b13.png',facecolor=fig.get_facecolor()); plt.close(fig)
print('done')
