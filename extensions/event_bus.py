class EventBus:
    def __init__(self):
        self.handlers:dict[str,list]={}

    def on(self,event:str,handler):
        self.handlers.setdefault(event, []).append(handler)

    def emit(self,event:str,*args,**kwargs):
        for handler in self.handlers.get(event,[]):
            result=handler(*args,**kwargs)
            if result and result.get("block"):
                return result
        return None