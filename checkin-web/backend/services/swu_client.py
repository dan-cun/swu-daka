class SwuClient:
    def login(self, *_args, **_kwargs) -> str:
        raise NotImplementedError("TODO: move login_and_checkin.py login flow into this client")

    def sync_today_task(self, *_args, **_kwargs) -> dict:
        raise NotImplementedError("TODO: implement cqtj/getTransitionByToday sync")

    def submit_checkin(self, *_args, **_kwargs) -> dict:
        raise NotImplementedError("TODO: implement getDormitory -> verify -> save")

