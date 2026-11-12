# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch
import numpy as np
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
fm.fontManager.addfont(FONT); plt.rcParams['font.family']=fm.FontProperties(fname=FONT).get_name(); plt.rcParams['axes.unicode_minus']=False
DARK='#24334d';GREEN='#2f5d46';MID='#5b8c6f';LIGHT='#a8c6b4';GREY='#8a94a6'
fig,ax=plt.subplots(figsize=(12,4.6),dpi=160); fig.patch.set_facecolor('#fbfcfa')
cats=['Q2 维持','随笔（转轨）'];vals=[104,5];cols=[MID,'#b9c3cf'];y=np.arange(2);bars=ax.barh(y,vals,color=cols,height=.5)
ax.set_yticks(y);ax.set_yticklabels(cats,fontsize=12,color=DARK);ax.invert_yaxis();ax.set_xlim(0,120)
for i,(b,v) in enumerate(zip(bars,vals)): ax.text(v+1,i,str(v),va='center',fontsize=13,color=DARK,fontweight='bold')
for s in ['top','right','left']: ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#c9d5cd');ax.tick_params(axis='x',labelsize=9,colors=GREY);ax.tick_params(axis='y',length=0);ax.grid(axis='x',color='#dde5df',linewidth=.7,alpha=.8);ax.set_axisbelow(True)
ax.set_xlabel('篇次',fontsize=9,color=GREY);ax.set_title('第 15 批剩余 Q2 收口：109 篇次',fontsize=18,color=DARK,fontweight='bold',loc='left',pad=16)
ax.text(0,1.02,'Q2 剩余 109 篇全量扫描；111、105、176、142、112 自述随笔，转轨后 Q2 实为 104 篇',transform=ax.transAxes,fontsize=9.3,color=GREY)
fig.text(.012,.012,'复核日期 2026-11-12  ·  109/109 正文存在，0 篇投稿模板残留  ·  全站收口',fontsize=8,color=GREY)
plt.subplots_adjust(left=.18,right=.96,top=.86,bottom=.18)
fig.savefig('rubbish/review-pack/batch-15-audit-109.png',facecolor=fig.get_facecolor());plt.close(fig)
grades=[('Q1 一区',45,GREEN),('Q2 二区',147,MID),('Q3 三区',34,LIGHT),('Q4 四区',2,'#d3dfd6'),('随笔不评级',46,'#b9c3cf')]
fig=plt.figure(figsize=(15,9.6),dpi=160);fig.patch.set_facecolor('#fbfcfa')
axh=fig.add_axes([0,.885,1,.115]);axh.axis('off');axh.add_patch(FancyBboxPatch((0,0),1,1,transform=axh.transAxes,facecolor=DARK,edgecolor='none',boxstyle='square,pad=0'))
axh.text(.045,.60,'RUBBISH 主编站点总览',fontsize=25,color='white',fontweight='bold',va='center');axh.text(.045,.27,'2026-11-12  ·  第 15 批 Q2 收口后  ·  全部稿件已审读',fontsize=10.5,color='#c9d5cd',va='center');axh.text(.965,.50,'274 篇  /  274 已审读',fontsize=12,color='#e8f0eb',ha='right',va='center')
kpis=[('全站稿件','274','paper 228 · essay 46'),('已人工审读','274','覆盖率 100%'),('已计分','228','Q1 45 · Q2 147 · Q3 34 · Q4 2'),('随笔不评级','46','essay 不套论文尺')]
for i,(k,v,s) in enumerate(kpis):
 ax=fig.add_axes([.055+i*.232,.745,.215,.115]);ax.axis('off');ax.add_patch(FancyBboxPatch((0,0),1,1,transform=ax.transAxes,facecolor='white',edgecolor='#dfe8e1',linewidth=1,boxstyle='round,pad=0.02,rounding_size=0.04'));ax.text(.08,.72,k,fontsize=11,color=GREY,va='center');ax.text(.08,.36,v,fontsize=30,color=DARK,fontweight='bold',va='center');ax.text(.08,.12,s,fontsize=8.8,color=GREEN,va='center')
ax1=fig.add_axes([.055,.095,.60,.56]);names=[g[0] for g in grades][::-1];counts=[g[1] for g in grades][::-1];cols=[g[2] for g in grades][::-1];y=np.arange(len(names));ax1.barh(y,counts,color=cols,height=.62);ax1.set_yticks(y);ax1.set_yticklabels(names,fontsize=11,color=DARK);ax1.set_xlim(0,170)
for i,v in enumerate(counts): ax1.text(v+2,i,str(v),va='center',fontsize=11,color=DARK,fontweight='bold')
for s in ['top','right','left']: ax1.spines[s].set_visible(False)
ax1.spines['bottom'].set_color('#c9d5cd');ax1.tick_params(axis='x',labelsize=9,colors=GREY);ax1.tick_params(axis='y',length=0);ax1.grid(axis='x',color='#dde5df',linewidth=.7,alpha=.8);ax1.set_axisbelow(True);ax1.set_title('年级分布（篇）',fontsize=14,color=DARK,fontweight='bold',loc='left',pad=12)
ax2=fig.add_axes([.70,.095,.265,.56]);ax2.axis('off');ax2.text(0,1.0,'站点侧样本',fontsize=14,color=DARK,fontweight='bold',va='top')
for i,(k,v) in enumerate([('注册用户','52'),('投稿','277'),('评论','7'),('论坛主题/回复','10 / 8'),('近 3 日访问','154')]):
 yy=.86-i*.17;ax2.text(0,yy,k,fontsize=10.5,color=GREY,va='center');ax2.text(.98,yy,v,fontsize=15,color=GREEN,fontweight='bold',va='center',ha='right')
ax2.text(0,.02,'page_views 仅保留 3 个自然日，样本不足，不作趋势结论。',fontsize=8,color=GREY,va='bottom')
fig.text(.012,.010,'第 15 批：剩余 Q2 109 篇全量收口；5 篇转 essay；全站 274 篇审读完成。',fontsize=8,color=GREY)
fig.savefig('rubbish/review-pack/site-overview-2026-11-12-b15.png',facecolor=fig.get_facecolor());plt.close(fig)
print('done')
