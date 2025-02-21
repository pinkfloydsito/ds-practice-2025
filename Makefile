test_bookstore_post:
	curl 'http://localhost:8081/checkout' \
	  -H 'Accept: */*' \
	  -H 'Accept-Language: en-US,en;q=0.9' \
	  -H 'Cache-Control: no-cache' \
	  -H 'Connection: keep-alive' \
	  -H 'Content-Type: application/json' \
	  -H 'DNT: 1' \
	  -H 'Origin: http://localhost:8080' \
	  -H 'Pragma: no-cache' \
	  -H 'Referer: http://localhost:8080/' \
	  -H 'Sec-Fetch-Dest: empty' \
	  -H 'Sec-Fetch-Mode: cors' \
	  -H 'Sec-Fetch-Site: same-site' \
	  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36' \
	  -H 'sec-ch-ua: "Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"' \
	  -H 'sec-ch-ua-mobile: ?0' \
	  -H 'sec-ch-ua-platform: "macOS"' \
	  --data-raw '{"user":{"name":"John Doe","contact":"john.doe@example.com"},"creditCard":{"number":"4111111111111111","expirationDate":"12/25","cvv":"123"},"userComment":"Please handle with care.","items":[{"name":"Book A","quantity":1},{"name":"Book B","quantity":2}],"billingAddress":{"street":"123 Main St","city":"Springfield","state":"IL","zip":"62701","country":"USA"},"shippingMethod":"Standard","giftWrapping":true,"termsAndConditionsAccepted":true}'
