from framework.helpers.tool import Response, Tool


class ResponseTool(Tool):
    async def execute(self, **kwargs):
        return Response(message=self.args["text"], break_loop=True)

    async def before_execution(self, **kwargs):
        self.log = self.agent.context.log.log(
            type="response",
            heading=f"{self.agent.agent_name}: Responding",
            content=self.args.get("text", ""),
        )

    async def after_execution(self, response, **kwargs):
        pass  # do not add anything to the history or output
