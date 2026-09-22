"""Illustrative broiler formulation. Reference composition, not a feed certificate.

All matrix percentages are as-fed; amino acids are poultry standardized ileal
digestible. Nutrient outputs exclude unknown premix carrier contributions.
See FEED_TRIAL_REVIEW.md for sources, assumptions and conditions before feeding.
"""
import json
from pathlib import Path

NAMES = ['me','cp','fat','fibre','ca','p','ap','na','cl','k','lys','met','mc','thr','val','ile','arg','trp','leu','choline','linoleic']
def row(values):
    return dict(zip(NAMES, values))

M = {
 'maize':row([3090,7.6,3.6,2.3,.04,.25,.06,.003,.05,.31,.21,.15,.32,.24,.35,.26,.34,.04,.87,532]),
 'fullfat':row([3210,36,18.4,5.6,.30,.56,.14,.005,.03,1.81,1.9,.44,.8,1.12,1.42,1.39,2.29,.34,2.25,2152]),
 'meal':row([2260,46.2,1.5,6,.34,.62,.14,.014,.03,2.09,2.53,.59,1.14,1.47,1.92,1.84,3.04,.57,3.07,2551]),
 'fish':row([3180,65.2,9.2,0,4.13,2.64,2.24,1.057,1.64,.79,4.33,1.57,1.98,2.39,2.8,2.37,3.62,.58,4.16,3812]),
 'oil':{'me':8980,'fat':99.8},
 'mcp':{'ca':16.7,'p':22.4,'ap':19.1,'na':.072,'cl':.01,'k':.23},
 'limestone':{'ca':37},
 'salt':{'na':39.3,'cl':60.7},
 'bicarbonate':{'na':27.37},
 'lysine':{'lys':78.8,'cl':19.1,'cp':94.4},
 'methionine':{'met':99,'mc':99,'cp':58.1},
 'threonine':{'thr':98.5,'cp':72.4},
 # 60% CHOLINE CHLORIDE supplies ~44.77% choline, NOT 60% choline.
 'choline60':{'choline':447700,'cl':15.24,'cp':37.62},
 'premix':{},
}
for ingredient,value in {'maize':1.83,'fullfat':9.54,'meal':.63,'fish':.14,'oil':51.2}.items():
    M[ingredient]['linoleic']=value

# Cobb500 medium/large bird phases 0-12, 13-28, 29-39 days.
# Final diet is adapted through day 42 by supplying >=3100 kcal/kg, while
# retaining Grower 2 amino-acid/mineral specifications (above Finisher 1).
TARGETS = {
 'starter':dict(me=2900,cp=22,ca=.96,ap=.58,lys=1.26,met=.48,mc=.94,thr=.86,val=.96,ile=.81,arg=1.36,trp=.21,leu=1.39),
 'grower':dict(me=2950,cp=20,ca=.80,ap=.40,lys=1.16,met=.47,mc=.88,thr=.78,val=.88,ile=.75,arg=1.25,trp=.18,leu=1.28),
 'finisher':dict(me=3050,cp=19,ca=.74,ap=.37,lys=1.06,met=.44,mc=.82,thr=.70,val=.81,ile=.69,arg=1.16,trp=.19,leu=1.17),
}
OLD = {
 'starter':dict(maize=24.045,fullfat=21.465,fish=2.445,premix=.15,salt=.15,mcp=.69,limestone=1,methionine=.055),
 'grower':dict(maize=28.44,fullfat=17.285,fish=2.81,premix=.15,salt=.125,mcp=.50,limestone=.64,methionine=.05),
 'finisher':dict(maize=27.705,fullfat=20.14,fish=.23,premix=.15,salt=.15,mcp=.695,limestone=.865,methionine=.065),
}

# Practical rounded recipes. Final maize weight balances each batch to 50 kg.
# PREMIX ASSUMPTION: 3 kg/t vitamin/trace-mineral premix, not concentrate;
# negligible macro-mineral carrier contribution; no added AA/choline.
# Must be recalculated if supplier product specifications differ.
TRIAL = {
 'starter':dict(meal=13,fullfat=5,fish=3,oil=1.640,mcp=.985,limestone=.335,premix=.150,salt=.065,bicarbonate=.145,lysine=.055,methionine=.160,threonine=.065,choline60=.060),
 'grower':dict(meal=12,fullfat=5,fish=2,oil=1.800,mcp=.630,limestone=.395,premix=.150,salt=.085,bicarbonate=.155,lysine=.070,methionine=.155,threonine=.060,choline60=.060),
 'finisher':dict(meal=11,fullfat=5,fish=1.5,oil=2.490,mcp=.615,limestone=.385,premix=.150,salt=.100,bicarbonate=.155,lysine=.065,methionine=.140,threonine=.040,choline60=.060),
}
for recipe in TRIAL.values():
    recipe['maize']=round(50-sum(recipe.values()),3)

def nutrients(recipe):
    total=sum(recipe.values())
    return {n:sum(w*M[i].get(n,0) for i,w in recipe.items())/total for n in NAMES}

def design(phase,meal,fullfat,fish):
    t=TARGETS[phase]
    r=dict(maize=25,meal=meal,fullfat=fullfat,fish=fish,premix=.15,choline60=.06)
    # Solve mass and energy together; recalculate minerals / amino acids.
    # Fixed protein inputs selected for AA adequacy, no least-cost objective.
    for _ in range(100):
        base={k:v for k,v in r.items() if k in ('maize','meal','fullfat','fish','premix','choline60')}
        contribution=lambda n:sum(w*M[i].get(n,0) for i,w in base.items())
        r['lysine']=max(0,(50*(t['lys']*1.03)-contribution('lys'))/78.8)
        r['methionine']=max(0,(50*(t['mc']*1.03)-contribution('mc'))/99)
        r['threonine']=max(0,(50*(t['thr']*1.03)-contribution('thr'))/98.5)
        r['mcp']=(50*(t['ap']+.01)-contribution('ap'))/19.1
        r['limestone']=(50*t['ca']-contribution('ca')-r['mcp']*16.7)/37
        r['salt']=(50*.25-contribution('cl')-r['lysine']*19.1-r['mcp']*.01)/60.7
        r['bicarbonate']=(50*.20-contribution('na')-r['salt']*39.3-r['mcp']*.072)/27.37
        other={k:v for k,v in r.items() if k not in ('maize','oil')}
        remaining=50-sum(other.values())
        other_energy=sum(w*M[i].get('me',0) for i,w in other.items())
        r['oil']=(50*(t['me']+60)-other_energy-remaining*M['maize']['me'])/(M['oil']['me']-M['maize']['me'])
        r['maize']=remaining-r['oil']
    return r

if __name__=='__main__':
    new=TRIAL
    out={'old':{p:{'recipe':r,'nutrients':nutrients(r)} for p,r in OLD.items()},'new':{p:{'recipe':r,'nutrients':nutrients(r)} for p,r in new.items()},'targets':TARGETS,'matrix':M}
    for phase,recipe in new.items():
        assert abs(sum(recipe.values())-50)<1e-8
        assert min(recipe.values())>=0
        result=nutrients(recipe)
        for nutrient,target in TARGETS[phase].items():
            assert result[nutrient]>=target-1e-8,(phase,nutrient,result[nutrient],target)
        assert .16<=result['na']<=.23
        assert .16<=result['cl']<=.30
        assert .60<=result['k']<=.95
        assert result['leu']/result['lys']<=1.45
        assert result['linoleic'] >= (1.2 if phase!='finisher' else 1.0)
        assert abs(result['ca']-TARGETS[phase]['ca'])<.02
        assert result['ap']-TARGETS[phase]['ap']<.025
    Path(__file__).with_name('feed_trial_calculations.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({p:out['new'][p] for p in new},indent=2))
