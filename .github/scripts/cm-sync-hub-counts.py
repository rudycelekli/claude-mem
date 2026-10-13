import json,re,sys
from pathlib import Path

def validate(text,files,tests,producer,writer):
    assert producer==0 and writer==0,'producer or artifact writer failed'
    assert files>0 and tests>0,'empty expected execution'
    text=re.sub(r'\x1b\[[0-9;]*m','',text)
    text=re.sub(r'(?m)^\ufeff?\d{4}-\d{2}-\d{2}T\S+Z\s+','',text)
    summaries=re.findall(r'(?m)^\s*(Test Files|Tests)\s+(.+?)\s*$',text)
    assert len(summaries)==2 and [x[0] for x in summaries]==['Test Files','Tests'],'missing or repeated framework summary'
    for (_,summary),wanted in zip(summaries,[files,tests]):
        match=re.fullmatch(r'(\d+) passed\s+\((\d+)\)',summary)
        assert match and int(match[1])==int(match[2])==wanted,'unexpected framework counts'
    return {'files':files,'passed':tests,'failed':0,'skipped':0,'producerExit':producer,'writerExit':writer}

def self_test():
    good='Test Files 7 passed (7)\nTests 141 passed (141)\nDuration 1.2s\n'
    assert validate(good,7,141,0,0)['passed']==141
    rejected=[]
    controls={
        'missing-summary':('Tests 141 passed (141)\n',7,141,0,0),
        'zero-summary':('Test Files 0 passed (0)\nTests 0 passed (0)\n',0,0,0,0),
        'unexpected-count':(good,7,140,0,0),
        'producer-error':(good,7,141,1,0),
        'tee-error':(good,7,141,0,1),
        'final-failure':(good+'Test Files 1 failed | 6 passed (7)\nTests 2 failed | 139 passed (141)\n',7,141,0,0),
        'skipped-tests':('Test Files 7 passed (7)\nTests 140 passed | 1 skipped (141)\n',7,141,0,0),
        'inconsistent-total':('Test Files 7 passed (7)\nTests 141 passed (142)\n',7,141,0,0),
    }
    for name,args in controls.items():
        try:validate(*args)
        except AssertionError:rejected.append(name)
        else:raise AssertionError('accepted invalid '+name)
    print(json.dumps({'selfTest':'PASS','positiveControls':1,'rejectedControls':rejected}))

if __name__=='__main__':
    if sys.argv[1:]==['--self-test']:self_test()
    else:print(json.dumps(validate(Path(sys.argv[1]).read_text(),*[int(v) for v in sys.argv[2:]]),sort_keys=True))
