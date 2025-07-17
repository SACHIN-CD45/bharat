// Main JavaScript file for Gym Management System

// Global Variables
let searchTimeout = null;
let currentStream = null;

// DOM Elements
const searchInput = document.getElementById('member-search');
const memberSearchResults = document.getElementById('search-results');
const notificationBadge = document.getElementById('notification-badge');
const notificationsList = document.getElementById('notifications-list');

// Camera Elements
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const photoPreview = document.getElementById('photo-preview');
const startButton = document.getElementById('start-camera');
const captureButton = document.getElementById('capture-photo');
const retakeButton = document.getElementById('retake-photo');
const photoData = document.getElementById('photo-data');

// Live Search Function
if (searchInput) {
    searchInput.addEventListener('input', function(e) {
        const query = e.target.value.trim();
        
        if (searchTimeout) {
            clearTimeout(searchTimeout);
        }
        
        if (query.length < 2) {
            memberSearchResults.innerHTML = '';
            memberSearchResults.classList.add('d-none');
            return;
        }
        
        searchTimeout = setTimeout(() => {
            fetch(`/api/search_members?query=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(data => {
                    memberSearchResults.innerHTML = '';
                            
                    if (data.members.length === 0) {
                        memberSearchResults.innerHTML = `
                            <div class="p-3 text-center text-muted">
                                <i class="fas fa-search mb-2"></i>
                                <p class="mb-0">No members found</p>
                            </div>
                        `;
                    } else {
                        data.members.forEach(member => {
                            const memberElement = document.createElement('div');
                            memberElement.className = 'search-item';
                            memberElement.innerHTML = `
                                <div class="d-flex align-items-center">
                                    <div class="me-3">
                                        ${member.photo 
                                            ? `<img src="/static/uploads/${member.photo}" alt="${member.name}">`
                                            : `<div class="rounded-circle bg-secondary d-flex align-items-center justify-content-center" style="width: 40px; height: 40px;">
                                                <i class="fas fa-user text-white"></i>
                                               </div>`
                                        }
                                    </div>
                                    <div>
                                        <h6 class="mb-1">${member.name}</h6>
                                        <p class="mb-0 text-muted small">${member.email}</p>
                                    </div>
                                </div>
                            `;
                            memberElement.addEventListener('click', () => {
                                window.location.href = `/member/${member._id}`;
                            });
                            memberSearchResults.appendChild(memberElement);
                        });
                    }
                    
                    memberSearchResults.classList.remove('d-none');
                })
                .catch(error => {
                    console.error('Error searching members:', error);
                });
        }, 300);
    });
    
    // Hide search results when clicking outside
    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !memberSearchResults.contains(e.target)) {
            memberSearchResults.classList.add('d-none');
        }
    });
}

// Camera Functions
if (startButton) {
    startButton.addEventListener('click', async function() {
        try {
            currentStream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = currentStream;
            await video.play();
            
            video.classList.remove('d-none');
            startButton.classList.add('d-none');
            captureButton.classList.remove('d-none');
            photoPreview.classList.add('d-none');
        } catch (err) {
            console.error("Error accessing camera:", err);
            alert("Could not access camera. Please make sure you have granted camera permissions.");
        }
    });
}

if (captureButton) {
    captureButton.addEventListener('click', function() {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        
        photoData.value = canvas.toDataURL('image/jpeg');
        photoPreview.src = photoData.value;
        
        video.classList.add('d-none');
        photoPreview.classList.remove('d-none');
        captureButton.classList.add('d-none');
        retakeButton.classList.remove('d-none');
        
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
    });
}

if (retakeButton) {
    retakeButton.addEventListener('click', function() {
        photoPreview.classList.add('d-none');
        retakeButton.classList.add('d-none');
        startButton.classList.remove('d-none');
        photoData.value = '';
    });
}

// Notification Functions
function updateNotificationBadge() {
    fetch('/api/notifications/unread/count')
        .then(response => response.json())
        .then(data => {
            if (notificationBadge) {
                if (data.count > 0) {
                    notificationBadge.textContent = data.count;
                    notificationBadge.classList.remove('d-none');
                } else {
                    notificationBadge.classList.add('d-none');
                }
            }
        })
        .catch(error => console.error('Error updating notifications:', error));
}

function markNotificationAsRead(notificationId) {
    fetch(`/mark_notification_read/${notificationId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const notification = document.querySelector(`[data-notification-id="${notificationId}"]`);
                if (notification) {
                    notification.classList.remove('unread');
                }
                updateNotificationBadge();
            }
        })
        .catch(error => console.error('Error marking notification as read:', error));
}

// PT Section Toggle
const needsPtCheckbox = document.getElementById('needs_pt');
const ptDetails = document.getElementById('pt_details');

if (needsPtCheckbox && ptDetails) {
    needsPtCheckbox.addEventListener('change', function() {
        if (this.checked) {
            ptDetails.classList.remove('d-none');
        } else {
            ptDetails.classList.add('d-none');
        }
    });
}

// Initialize tooltips
document.addEventListener('DOMContentLoaded', function() {
    const tooltips = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltips.map(function(tooltip) {
        return new bootstrap.Tooltip(tooltip);
    });
    
    // Start notification polling
    if (notificationBadge) {
        updateNotificationBadge();
        setInterval(updateNotificationBadge, 30000); // Check every 30 seconds
    }
    
    const subscriptionOptions = document.querySelectorAll('input[name="subscription_plan"]');
    const razorpayButton = document.getElementById('razorpay-button');
    const phonepeButton = document.getElementById('phonepe-button');

    function getSelectedPlanAmount() {
        const selectedPlan = document.querySelector('input[name="subscription_plan"]:checked');
        if (!selectedPlan) {
            alert('Please select a subscription plan.');
            return null;
        }

        let amount = 0;
        switch (selectedPlan.value) {
            case 'one_month':
                amount = 49900; // Amount in paise
                break;
            case 'three_months':
                amount = 129900;
                break;
            case 'six_months':
                amount = 199900;
                break;
            case 'one_year':
                amount = 299900;
                break;
            default:
                alert('Invalid subscription plan selected.');
                return null;
        }
        return amount;
    }

    razorpayButton.addEventListener('click', function() {
        const amount = getSelectedPlanAmount();
        if (amount === null) return;

        const options = {
            key: 'YOUR_RAZORPAY_KEY', // Replace with your Razorpay key
            amount: amount,
            currency: 'INR',
            name: 'GYMTRACK',
            description: 'Subscription Payment',
            handler: function(response) {
                alert('Payment successful. Payment ID: ' + response.razorpay_payment_id);
                // Optionally, send the payment ID to your server for further processing
            },
            prefill: {
                name: '{{ current_user.user_data.name }}',
                email: '{{ current_user.user_data.email }}'
            },
            theme: {
                color: '#F37254'
            }
        };

        const rzp1 = new Razorpay(options);
        rzp1.open();
    });

    phonepeButton.addEventListener('click', function() {
        const amount = getSelectedPlanAmount();
        if (amount === null) return;

        // PhonePe payment integration logic
        // This is a placeholder. Replace with actual PhonePe integration code.
        alert('PhonePe payment integration is not yet implemented.');
    });

    subscriptionOptions.forEach(option => {
        option.addEventListener('change', function() {
            console.log(`Selected plan: ${this.value}`);
        });
    });
});

document.addEventListener('DOMContentLoaded', function() {
    const renewButton = document.querySelector('.renew-subscription button');
    if (renewButton) {
        renewButton.addEventListener('click', function() {
            const selectedPlan = document.querySelector('input[name="subscription_plan"]:checked');
            if (selectedPlan) {
                const planValue = selectedPlan.value;
                fetch('/process_payment', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded'
                    },
                    body: `subscription_plan=${planValue}`
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(data.message);
                        window.location.href = '/dashboard';
                    } else {
                        alert(data.message);
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    alert('An error occurred while processing your request.');
                });
            } else {
                alert('Please select a subscription plan to renew.');
            }
        });
    }
});

// Clean up on page unload
window.addEventListener('beforeunload', function() {
    if (currentStream) {
        currentStream.getTracks().forEach(track => track.stop());
    }
});

const searchInputs = document.querySelectorAll('.search-input');
const searchResults = document.querySelectorAll('.search-results');

searchInputs.forEach(input => {
    input.addEventListener('input', function(e) {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();
        
        if (query.length < 1) {
            searchResults.forEach(result => {
                result.innerHTML = '';
                result.classList.remove('show');
            });
            return;
        }

        // Show loading state
        searchResults.forEach(result => {
            result.innerHTML = '<div class="search-result-empty">Searching...</div>';
            result.classList.add('show');
        });

        searchTimeout = setTimeout(() => {
            fetch(`/search?query=${encodeURIComponent(query)}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Search request failed');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.length > 0) {
                        const html = data.map(item => `
                            <a href="${item.url}" class="search-result-item">
                                <div class="d-flex align-items-center">
                                    <div class="search-result-icon ${item.type === 'Member' ? 'bg-primary' : 'bg-success'}">
                                        <i class="fas ${item.type === 'Member' ? 'fa-user' : 'fa-dumbbell'}"></i>
                                    </div>
                                    <div class="search-result-info">
                                        <div class="search-result-name">${item.name}</div>
                                        <div class="search-result-details">
                                            ${item.type === 'Member' ? 
                                                `<span class="badge ${item.status === 'Active' ? 'bg-success' : 'bg-danger'}">${item.status}</span>` :
                                                `<span class="badge bg-info">${item.specialization || 'Trainer'}</span>`
                                            }
                                            <small class="text-muted">${item.phone}</small>
                                        </div>
                                    </div>
                                </div>
                            </a>
                        `).join('');
                        searchResults.forEach(result => {
                            result.innerHTML = html;
                        });
                    } else {
                        searchResults.forEach(result => {
                            result.innerHTML = '<div class="search-result-empty">No results found</div>';
                        });
                    }
                })
                .catch(error => {
                    console.error('Search error:', error);
                    searchResults.forEach(result => {
                        result.innerHTML = '<div class="search-result-empty text-danger">Error performing search</div>';
                    });
                });
        }, 300);
    });
});

// Hide search results when clicking outside
document.addEventListener('click', function(e) {
    searchInput.forEach(input => {
        searchResults.forEach(result => {
            if (!input.contains(e.target) && !result.contains(e.target)) {
                result.classList.remove('show');
            }
        });
    });
});

// Update notification count
function updateNotificationCount() {
    fetch('/api/notifications/count')
        .then(response => response.json())
        .then(data => {
            const badge = document.getElementById('notification-badge');
            if (data.count > 0) {
                badge.textContent = data.count;
                badge.classList.remove('d-none');
            } else {
                badge.classList.add('d-none');
            }
        });
}

document.getElementById('paymentForm').onsubmit = function(event) {
    // You can add any additional validation or processing here before submission
    alert('Payment plan selected: ' + document.querySelector('input[name="plan"]:checked').value);
};

// Example code to create a chart (using Chart.js)
const ctx = document.getElementById('earningsChart').getContext('2d');
const earningsChart = new Chart(ctx, {
    type: 'bar',
    data: {
        labels: ['1 Month', '3 Months', '6 Months', '1 Year'],
        datasets: [{
            label: 'Earnings',
            data: [29.99, 79.99, 139.99, 249.99], // Replace with dynamic data if needed
            backgroundColor: 'rgba(75, 192, 192, 0.6)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1
        }]
    },
    options: {
        scales: {
            y: {
                beginAtZero: true
            }
        }
    }
});
// payment
document.getElementById('razorpay-button').onclick = function (e) {
    var options = {
        key: 'YOUR_RAZORPAY_KEY', // Enter the Key ID generated from the Dashboard
        amount: 50000, // Amount is in currency subunits. Default is paise. Hence 50000 means ₹500.
        currency: "INR",
        name: "Your Website Name",
        description: "Test Transaction",
        image: "https://your-logo-url.com",
        order_id: '', // Pass the order_id obtained from the server
        handler: function (response) {
            // Handle successful payment here
            alert(response.razorpay_payment_id);
            // Optionally, send the payment ID to your server for further processing
        },
        prefill: {
            name: "Customer Name",
            email: "customer@example.com",
            contact: "9999999999"
        },
        notes: {
            address: "Customer Address"
        },
        theme: {
            color: "#F37254"
        }
    };
    var rzp1 = new Razorpay(options);
    rzp1.open();
    e.preventDefault();
};
// Update notification count every minute
setInterval(updateNotificationCount, 60000);
updateNotificationCount();