from locust import HttpUser, between, task


class ServiceUser(HttpUser):
	wait_time = between(0.1, 1.0)

	@task(3)
	def cpu_work(self) -> None:
		self.client.get("/work/cpu", name="/work/cpu")

	@task(2)
	def io_work(self) -> None:
		self.client.get("/work/io", name="/work/io")

	@task(1)
	def health(self) -> None:
		self.client.get("/health", name="/health")
