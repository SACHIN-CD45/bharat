// Main JavaScript file for Gym Management System

// Global Variables
let searchTimeout = null;
let currentStream = null;

// DOM Elements
const searchInput = document.getElementById('member-search');
const searchResults = document.getElementById('search-results');
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
            searchResults.innerHTML = '';
            searchResults.classList.add('d-none');
            return;
        }
        
        searchTimeout = setTimeout(() => {
            fetch(`/api/search_members?query=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(data => {
                    searchResults.innerHTML = '';
                    
                    if (data.members.length === 0) {
                        searchResults.innerHTML = `
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
                            searchResults.appendChild(memberElement);
                        });
                    }
                    
                    searchResults.classList.remove('d-none');
                })
                .catch(error => {
                    console.error('Error searching members:', error);
                });
        }, 300);
    });
    
    // Hide search results when clicking outside
    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
            searchResults.classList.add('d-none');
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
});

// Clean up on page unload
window.addEventListener('beforeunload', function() {
    if (currentStream) {
        currentStream.getTracks().forEach(track => track.stop());
    }
});
