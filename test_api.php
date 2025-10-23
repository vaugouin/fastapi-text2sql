<?php
/**
 * PHP Test Script for FastAPI Text2SQL API
 * Tests the /search/text2sql POST endpoint with various scenarios
 */
set_time_limit(0);

// Display script start time
echo "<h2>FastAPI Text2SQL API Test Script</h2>";
echo "<p><strong>Script started at:</strong> " . date('Y-m-d H:i:s') . "</p>";
echo "<hr>";

// Configuration
require("global-light-secrets.inc.php");

$api_base_url = $strtext2sqlapigreendomainurl;

/**
 * Function to make API requests using curl
 */
function callAPI($url, $data, $strtext2sqlapikeyvalue) {
    $ch = curl_init();
    
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json',
        'X-API-Key: ' . $strtext2sqlapikeyvalue
    ]);
    curl_setopt($ch, CURLOPT_TIMEOUT, 30);
    
    $response = curl_exec($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    
    curl_close($ch);
    
    return [
        'http_code' => $http_code,
        'response' => $response,
        'error' => $error
    ];
}

/**
 * Function to display test results
 */
function displayResult($test_name, $result) {
    echo "<br />" . str_repeat("=", 60) . "<br />";
    echo "TEST: $test_name<br />";
    echo str_repeat("=", 60) . "<br />";
    
    if ($result['error']) {
        echo "CURL ERROR: " . $result['error'] . "<br />";
        return;
    }
    
    echo "HTTP Code: " . $result['http_code'] . "<br />";
    
    if ($result['http_code'] == 200) {
        $response_data = json_decode($result['response'], true);
        if ($response_data) {
            echo "Status: SUCCESS<br />";
            echo "Question: " . $response_data['question'] . "<br />";
            echo "Question Hash: " . ($response_data['question_hashed'] ?? 'N/A') . "<br />";
            echo "SQL Query: " . $response_data['sqlquery'] . "<br />";
            echo "Processing Time: " . $response_data['processing_time'] . "s<br />";
            echo "Query Execution Time: " . $response_data['query_execution_time'] . "s<br />";
            echo "Cached: " . ($response_data['cached'] ? 'Yes' : 'No') . "<br />";
            //echo "LLM Model: " . $response_data['llm_model'] . "<br />";
            echo "Results Count: " . count($response_data['result']) . "<br />";
            
            // Show first few results if any
            if (!empty($response_data['result']) && !isset($response_data['result'][0]['error'])) {
                echo "Sample Results:<br />";
                for ($i = 0; $i < min(3, count($response_data['result'])); $i++) {
                    echo "  Row " . $response_data['result'][$i]['index'] . ": " . 
                         json_encode($response_data['result'][$i]['data']) . "<br />";
                }
            } elseif (!empty($response_data['result']) && isset($response_data['result'][0]['error'])) {
                echo "Query Error: " . $response_data['result'][0]['error'] . "<br />";
            }
        } else {
            echo "Status: ERROR - Invalid JSON response<br />";
            echo "Raw Response: " . $result['response'] . "<br />";
        }
    } else {
        echo "Status: ERROR<br />";
        echo "Response: " . $result['response'] . "<br />";
    }
}

// Test the hello world endpoint first
echo "Testing FastAPI Text2SQL API<br />";
echo "Using API Base URL: $api_base_url<br />";

$hello_result = callAPI($api_base_url . "/", [], $strtext2sqlapikeyvalue);
displayResult("Hello World Endpoint", $hello_result);

// Test cases for the /search/text2sql endpoint
$test_cases = [
    [
        'name' => 'Basic Question with Cache Storage',
        'data' => [
            'question' => 'TV series created by Alfred Hitchcock',
            'retrieve_from_cache' => true,
            'store_to_cache' => true,
            'llm_model' => 'gpt-4'
        ]
    ],
    [
        'name' => 'Basic Question with Cache Storage',
        'data' => [
            'question' => 'Donne-moi 10 films en couleurs dans lesquels Humphrey Bogart joue un rôle',
            'retrieve_from_cache' => true,
            'store_to_cache' => true,
            'llm_model' => 'gpt-4'
        ]
    ],
    [
        'name' => 'Basic Question with Cache Storage',
        'data' => [
            'question' => 'Donne moi les 50 comédies de long métrage en langue anglaise des années 50 avec les meilleurs notes IMDb',
            'retrieve_from_cache' => true,
            'store_to_cache' => true,
            'llm_model' => 'gpt-4'
        ]
    ],
    [
        'name' => 'Question with Pagination',
        'data' => [
            'question' => 'Most popular Japanese directors',
            'page' => 1,
            'retrieve_from_cache' => true,
            'store_to_cache' => true,
            'llm_model' => 'default'
        ]
    ],
    [
        'name' => 'Question with Pagination',
        'data' => [
            'question' => 'Most popular Japanese directors',
            'page' => 2,
            'retrieve_from_cache' => true,
            'store_to_cache' => true,
            'llm_model' => 'default'
        ]
    ],
    [
        'name' => 'Question with Disambiguation Data',
        'data' => [
            'question' => 'Films d\'aventure avec Harrison Ford',
            'disambiguation_data' => [
                'location_type' => 'city',
                'country' => 'USA'
            ],
            'retrieve_from_cache' => true,
            'store_to_cache' => true
        ]
    ],
    [
        'name' => 'Cache Retrieval Only (No Storage)',
        'data' => [
            'question' => 'TV series created by Alfred Hitchcock', // Same as first test to test cache hit
            'retrieve_from_cache' => true,
            'store_to_cache' => true,
            'llm_model' => 'gpt-4'
        ]
    ],
    [
        'name' => 'Question Hash Only (Simulating Pagination)',
        'data' => [
            'question_hashed' => hash('sha256', 'TV series created by Alfred Hitchcock'), // Hash of first question
            'page' => 1,
            'retrieve_from_cache' => true,
            'store_to_cache' => true
        ]
    ],
    [
        'name' => 'No Cache Operations',
        'data' => [
            'question' => 'Nombre de films réalisés par Martin Scorsese',
            'retrieve_from_cache' => true,
            'store_to_cache' => true,
            'llm_model' => 'claude'
        ]
    ]
];

// Execute test cases
foreach ($test_cases as $test_case) {
    $result = callAPI($api_base_url . "/search/text2sql", $test_case['data'], $strtext2sqlapikeyvalue);
    displayResult($test_case['name'], $result);
    
    // Add a small delay between requests
    sleep(1);
}

// Test error cases
echo "<br />" . str_repeat("=", 60) . "<br />";
echo "TESTING ERROR CASES<br />";
echo str_repeat("=", 60) . "<br />";

// Test with missing question and question_hashed
$error_test = callAPI($api_base_url . "/search/text2sql", [
    'page' => 1,
    'retrieve_from_cache' => true
], $strtext2sqlapikeyvalue);
displayResult("Missing Question and Hash (Should Fail)", $error_test);

// Test with invalid API key
$invalid_key_test = callAPI($api_base_url . "/search/text2sql", [
    'question' => 'Test question'
], 'invalid-api-key');
displayResult("Invalid API Key (Should Fail)", $invalid_key_test);

echo "<br />" . str_repeat("=", 60) . "<br />";
echo "API TESTING COMPLETED<br />";
echo str_repeat("=", 60) . "<br />";

?>
