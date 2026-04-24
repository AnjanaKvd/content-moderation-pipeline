# USE: locust (pip install locust)
# RUN: locust -f tests/locust_loadtest.py --host=https://your-aca-url.azurecontainerapps.io
#      Then open http://localhost:8089 and set:
#      Users: 100, Spawn rate: 10/sec, Run time: 2 min

from locust import HttpUser, task, between
import random

TOXIC_COMMENTS = [
    "I hate everyone here",
    "This is the worst product ever made",
    "You are all idiots",
    "Absolutely terrible service, never coming back",
    "You people are disgusting",
    "Worst experience of my life",
    "This app is garbage and so are the developers",
    "I will destroy your reputation",
    "Shut up and go away",
    "Nobody likes you here",
    "Your support team is useless",
    "Completely broken and worthless",
    "Trash company run by trash people",
    "Die in a fire",
    "I hope this company fails",
    "Garbage trash app",
    "Ridiculous incompetence everywhere",
    "You are a disease on this platform",
    "The moderators are corrupt",
    "Horrible people, horrible product",
    "Burn it all down",
    "Pathetic losers running this place",
]

CLEAN_COMMENTS = [
    "Great product, highly recommend!",
    "The weather is lovely today",
    "Just checking in, hope you are well",
    "Amazing quality, will buy again",
    "Thanks for the quick support response",
    "Love the new features in this update",
    "Fantastic experience from start to finish",
    "Best purchase I've made this year",
    "Keep up the excellent work team",
    "Super smooth and intuitive interface",
    "Highly recommended for beginners",
    "Wonderful community here",
    "Exactly what I was looking for",
    "Fast shipping and great packaging",
    "Appreciate all the hard work",
    "So happy I discovered this app",
    "Five stars without hesitation",
    "Clean design and easy to use",
    "Reliable and consistent performance",
    "Looking forward to future updates",
    "Nicely done on the latest release",
    "Pleasantly surprised by the quality",
]


class ModerationUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(8)
    def moderate_single(self):
        comment = random.choice(TOXIC_COMMENTS + CLEAN_COMMENTS)
        if random.random() > 0.5:
            comment += f" {random.randint(1, 1000000)}"
        self.client.post("/moderate", json={"comment": comment})

    @task(2)
    def moderate_batch(self):
        comments = [
            {"comment": random.choice(TOXIC_COMMENTS + CLEAN_COMMENTS)}
            for _ in range(random.randint(10, 50))
        ]
        self.client.post("/moderate/batch", json={"comments": comments})

    @task(1)
    def health_check(self):
        self.client.get("/health")


# TARGET METRICS TO SCREENSHOT:
# - p95 latency < 100ms (with cache hits mixed in)
# - 0% error rate at 100 concurrent users
# - Requests/sec > 50
