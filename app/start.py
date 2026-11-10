import os
import uvicorn
from .db import init
from .seed import main

if __name__=='__main__':
    init()
    if os.environ.get('SEED_DEMO','1')=='1': main()
    uvicorn.run('app.main:app',host='0.0.0.0',port=8000)
