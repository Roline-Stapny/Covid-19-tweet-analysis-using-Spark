import json, requests, sys
from nltk.corpus import stopwords
from operator import add
from pyspark import SparkContext
from pyspark.streaming import StreamingContext
from pyspark.streaming.kafka import KafkaUtils
from pyspark.streaming.kafka import TopicAndPartition


def sendTopWords(counts, url):
    def takeAndSend(time, rdd):
        if not rdd.isEmpty():
            word_counts = rdd.take(10)

            words = []
            values = []

            for (word, count) in word_counts:
                words.append(word)
                values.append(count)

            json_data = {'words': str(words), 'counts': str(values)}
            print(json_data)

            response = requests.post(url, data=json_data)

    counts.foreachRDD(takeAndSend)


def sendTweets(tweets, url):
    def takeAndSend(time, rdd):
        if not rdd.isEmpty():
            tweets_data = rdd.take(10)

            users = []
            texts = []

            for (user, text, follower_count) in tweets_data:
                users.append(user)
                texts.append(text)

            json_data = {'user': str(users), 'text': str(texts)}
            print(json_data)

            response = requests.post(url, data=json_data)

    tweets.foreachRDD(takeAndSend)


def sendGeoData(path, url):
    filepath = "file:///" + path
    geodata = sc.textFile(filepath) \
                .map(lambda x: x.encode("ascii", "ignore")) \
                .map(lambda x: json.loads(x)) \
                .map(lambda json_object: (json_object["user"]["screen_name"], json_object["coordinates"])) \
                .map(lambda kv: (kv[1]['coordinates'][0], kv[1]['coordinates'][1])) \
                .collect()

    longitudes = []
    latitudes = []

    for geotweet in geodata:
        longitudes.append(geotweet[0])
        latitudes.append(geotweet[1])

    json_data = {'longitude': str(longitudes), 'latitude': str(latitudes)}
    print(json_data)

    response = requests.post(url, data=json_data)


def sendTweetsFromStream(kvs, url):
    tweets = kvs.map(lambda x: x[1].encode("ascii", "ignore")) \
                .map(lambda x: json.loads(x)) \
                .map(lambda json_object: (json_object["user"]["screen_name"], json_object["text"], json_object["user"]["followers_count"])) \
                .transform(lambda rdd: rdd.sortBy(lambda x: x[2], ascending = False))
    tweets.pprint()
    sendTweets(tweets, url)


def sendTopHashtagsFromStream(kvs, url):
    tweets = kvs.map(lambda x: x[1].encode("ascii", "ignore")) \
                .map(lambda x: json.loads(x)) \
                .map(lambda json_object: (json_object["user"]["screen_name"], json_object["text"]))

    lines = tweets.flatMap(lambda line: line[1].split(" "))

    ## This part does the hashtag count
    hashtag_counts = lines.filter(lambda word: len(word) >= 2 and word[0] == '#') \
                          .map(lambda word: (word, 1)) \
                          .reduceByKey(add) \
                          .transform(lambda rdd: rdd.sortBy(lambda x: x[1], ascending = False))
    hashtag_counts.pprint()
    sendTopWords(hashtag_counts, url)


def sendTopWordsFromStream(kvs, url):
    tweets = kvs.map(lambda x: x[1].encode("ascii", "ignore")) \
                .map(lambda x: json.loads(x)) \
                .map(lambda json_object: (json_object["user"]["screen_name"], json_object["text"]))

    lines = tweets.flatMap(lambda line: line[1].split(" "))

    ## This part does the word count
    sw = stopwords.words('english')
    sw.extend(['rt', 'https', 'http', 'coronavirus', 'covid19', 'covid-19'])

    counts = lines.map(lambda word: word.strip().lower()) \
                  .filter(lambda word: word not in sw) \
                  .filter(lambda word: len(word) >= 2 and word[0] != '#' and word[0] != '@') \
                  .map(lambda word: (word, 1)) \
                  .reduceByKey(add) \
                  .transform(lambda rdd: rdd.sortBy(lambda x: x[1], ascending = False))
    counts.pprint()
    sendTopWords(counts, url)


if __name__ == "__main__":
    sc = SparkContext(appName = "TwitterDataAnalysis")
    sc.setLogLevel("ERROR")

    ssc = StreamingContext(sc, 10)
    brokers, topic, geodata_path = sys.argv[1:]
    
    server = 'http://localhost:5000/'
    sendGeoData(geodata_path, server + 'update_geodata') 

    kvs = KafkaUtils. \
        createDirectStream(ssc, [topic], {"metadata.broker.list": brokers, "auto.offset.reset": "smallest"})

    sendTweetsFromStream(kvs, server + 'update_tweets')
    sendTopHashtagsFromStream(kvs, server + 'update_hashtagcounts')
    sendTopWordsFromStream(kvs, server + 'update_counts')

    ssc.start()
    ssc.awaitTerminationOrTimeout(60)
    ssc.stop(stopGraceFully = True)
