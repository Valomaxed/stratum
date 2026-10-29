"""Plot saved numerical verification data; run in the optional plotting runtime."""
import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main(directory):
    directory=Path(directory)
    report=json.loads((directory/'report.json').read_text(encoding='utf8'))
    archive=np.load(directory/'histories.npz')
    systems=('unbraced','x','chevron');labels=('Unbraced','X-braced','Chevron')
    colors=('#2563eb','#c65b13','#007f65')
    plt.rcParams.update({'font.family':'Arial','font.size':9,'axes.spines.top':False,
        'axes.spines.right':False,'axes.grid':True,'grid.alpha':.18,'savefig.facecolor':'white'})
    fig,axes=plt.subplots(3,2,figsize=(12,8),sharex=True,layout='constrained')
    for i,(system,label,color) in enumerate(zip(systems,labels,colors)):
        prefix='el-centro-default-4-story__'+system
        t=archive[prefix+'__stratum_time_s']
        for j,(skey,okey,multiplier) in enumerate((('roof_mm','displacement_m',1000),('base_shear_kn','base_shear_kn',1))):
            ax=axes[i,j];s=archive[prefix+'__stratum_'+skey];o=archive[prefix+'__opensees_'+okey]
            if j==0:o=o[:,-1]*multiplier
            ax.plot(t,s,color=color,lw=1.3,label='Stratum')
            ax.plot(t,o,color='#20252a',lw=.8,ls='--',label='OpenSees')
            ax.set_ylabel(label+'\n'+('Roof displacement (mm)' if j==0 else 'Base shear demand (kN)'))
            if i==0:ax.legend(loc='upper right',fontsize=8)
            if i==2:ax.set_xlabel('Time (s)')
    fig.suptitle('Stratum vs independent OpenSees model · El Centro 1940 N–S',fontsize=14)
    fig.savefig(directory/'opensees-comparison.png',dpi=180)
    plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(12,4.2),layout='constrained')
    metrics=('peak_drift_pct','peak_roof_mm','peak_base_shear_kn')
    titles=('Peak interstory drift','Peak roof displacement','Peak base shear demand')
    for ax,key,title in zip(axes,metrics,titles):
        for row,label,color,style in zip(report['convergence'],labels,colors,('-','--',':')):
            p=row['peaks'][key]
            differences=[100*abs(value-p['quarter'])/max(abs(p['quarter']),1e-14)
                         for value in (p['production'],p['half'],p['quarter'])]
            ax.plot([1,2,4],differences,marker='o',ms=4,color=color,ls=style,label=label)
        ax.set_xticks([1,2,4],['dt','dt / 2','dt / 4']);ax.set_title(title,fontsize=10);ax.set_xlabel('Integration refinement')
        ax.set_ylabel('Absolute change from dt / 4 peak (%)')
    axes[-1].legend(fontsize=8)
    fig.suptitle('Time-step refinement · El Centro 1940 N–S · dt / 4 is the reference, not an exact solution',fontsize=12)
    fig.savefig(directory/'time-step-convergence.png',dpi=180)
    plt.close(fig)


if __name__=='__main__':main(sys.argv[1])
