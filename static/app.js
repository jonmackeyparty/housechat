// Client-side Socket.IO logic for Mein Chat
(function(){
    var cfg = window.MC_CONFIG || {};
    var currentChannel = cfg.channel || '';
    // Prevent the browser's immediate jump to an anchor on navigation so we can smooth-scroll instead
    try {
        if ('scrollRestoration' in history) {
            history.scrollRestoration = 'manual';
        }
    } catch (e) {}
    if (window.location && window.location.hash && window.location.hash.indexOf('#msg-') === 0) {
        try { window.scrollTo(0, 0); } catch (e) {}
    }

    function renderReactions(msg) {
        if (!msg.reactions || msg.reactions.length === 0) return '';
        return '<div class="reactions" style="margin:6px 0;">' + msg.reactions.map(function(r){
            return '<span class="emoji-btn" style="background:#ffe4c4; border:none; cursor:default;">'+ r +'</span>';
        }).join('') + '</div>';
    }

    function renderReplies(msg) {
        var replies = (msg.replies || []).slice();
        // sort replies by timestamp (ascending) so display order is oldest -> newest
        replies.sort(function(a,b){
            var ta = a && a.timestamp ? a.timestamp : '';
            var tb = b && b.timestamp ? b.timestamp : '';
            if (ta < tb) return -1;
            if (ta > tb) return 1;
            return 0;
        });
        if (replies.length === 0) return '';
        var count = replies.length;
        var html = '<div class="replies" data-count="' + count + '">';
        // preview should show the first two (oldest) replies; the rest are hidden until expanded
        // preview: first up to 2 replies (oldest)
        var preview = replies.slice(0, 2);
        // build preview first so it's always at the top
        // (preview already built above)
        // build preview first so it's always at the top
        html += '<div class="replies-preview">';
        preview.forEach(function(reply){
            var ts = reply.timestamp ? '<span class="reply-ts"> ' + escapeHtml(reply.timestamp) + '</span>' : '';
            var rAvatar = '<div class="reply-avatar">' + escapeHtml((reply.user||' ')[0]||'?') + '</div>';
            if (reply.avatar) {
                if (reply.avatar.url) {
                    rAvatar = '<div class="reply-avatar"><img src="' + escapeHtml(reply.avatar.url) + '" alt="' + escapeHtml(reply.user) + '"/></div>';
                } else {
                    rAvatar = '<div class="reply-avatar" style="background:' + escapeHtml(reply.avatar.bg || '#888') + '; color:' + escapeHtml(reply.avatar.fg || '#fff') + ';">' + escapeHtml(reply.avatar.initials || (reply.user||' ')[0]) + '</div>';
                }
            }
            html += '<div class="reply-item">' + rAvatar + '<div class="reply-content"><div class="reply-meta"><strong>' + escapeHtml(reply.user) + '</strong>' + ts + '</div><div class="reply-text">' + escapeHtml(reply.message) + '</div></div></div>';
        });
        html += '</div>';
        // now build the hidden block containing the remaining (newer) replies so they appear below the preview when expanded
        var rest = replies.length > 2 ? replies.slice(2) : [];
        if (rest.length) {
            html += '<div class="replies-full" style="display:none;">';
            rest.forEach(function(reply){
                var ts = reply.timestamp ? '<span class="reply-ts"> ' + escapeHtml(reply.timestamp) + '</span>' : '';
                var rAvatar = '<div class="reply-avatar">' + escapeHtml((reply.user||' ')[0]||'?') + '</div>';
                if (reply.avatar) {
                    if (reply.avatar.url) {
                        rAvatar = '<div class="reply-avatar"><img src="' + escapeHtml(reply.avatar.url) + '" alt="' + escapeHtml(reply.user) + '"/></div>';
                    } else {
                        rAvatar = '<div class="reply-avatar" style="background:' + escapeHtml(reply.avatar.bg || '#888') + '; color:' + escapeHtml(reply.avatar.fg || '#fff') + ';">' + escapeHtml(reply.avatar.initials || (reply.user||' ')[0]) + '</div>';
                    }
                }
                html += '<div class="reply-item">' + rAvatar + '<div class="reply-content"><div class="reply-meta"><strong>' + escapeHtml(reply.user) + '</strong>' + ts + '</div><div class="reply-text">' + escapeHtml(reply.message) + '</div></div></div>';
            });
            html += '</div>';
        }
        if (count > 2) {
            html += '<button class="replies-toggle">View ' + count + ' replies</button>';
        }
        html += '</div>';
        return html;
    }

    // delegate click handler for replies toggle
    document.addEventListener('click', function(e){
        if (!e.target.matches) return;
        if (e.target.matches('.replies-toggle')) {
            var btn = e.target;
            var container = btn.closest('.replies');
            if (!container) return;
            var full = container.querySelector('.replies-full');
            if (!full) return;
            if (full.style.display === 'none' || full.style.display === '') {
                full.style.display = 'block';
                btn.textContent = 'Hide replies';
                // smooth-scroll to the first newly revealed reply to avoid a small jump
                setTimeout(function(){
                    var first = full.querySelector('.reply-item');
                    if (first && first.scrollIntoView) first.scrollIntoView({behavior: 'smooth', block: 'nearest'});
                }, 60);
            } else {
                full.style.display = 'none';
                var cnt = container.dataset.count || '';
                btn.textContent = cnt ? ('View ' + cnt + ' replies') : 'View replies';
            }
        }
    });

    // Smooth scroll to anchored message after page load to reduce visual jump
    window.addEventListener('load', function(){
        try {
            var h = window.location.hash;
            if (h && h.indexOf('#msg-') === 0) {
                var el = document.querySelector(h);
                if (el && el.scrollIntoView) {
                    setTimeout(function(){ el.scrollIntoView({behavior: 'smooth', block: 'center'}); }, 60);
                }
            }
        } catch (err) {
            // ignore
        }
    });

    // Intercept form submissions for composer, reply and reaction forms to avoid full-page reloads
    // track last clicked submit button so we can include its name/value when submitting via fetch
    var _lastClickedSubmit = null;
    document.addEventListener('click', function(ev){
        try {
            var b = ev.target;
            if (b && (b.tagName || '').toLowerCase() === 'button' && b.type === 'submit') {
                _lastClickedSubmit = b;
            }
        } catch (err) {}
    }, true);

    document.addEventListener('submit', function(e){
        var form = e.target;
        if (!form || !form.action) return;
        // composer (new message)
        if (form.matches('.composer') || (form.action.indexOf('/channel/') !== -1 && form.querySelector('input[name="message"]')) ) {
            e.preventDefault();
            var fd = new FormData(form);
            // include clicked submit button value if present (e.g., emoji reaction buttons)
            try {
                if (_lastClickedSubmit && _lastClickedSubmit.form === form && _lastClickedSubmit.name) {
                    fd.append(_lastClickedSubmit.name, _lastClickedSubmit.value);
                }
            } catch (err) {}
            fetch(form.action, { method: 'POST', body: fd, credentials: 'same-origin' }).catch(function(){ /* ignore */ });
            _lastClickedSubmit = null;
            // don't try to scroll immediately; socket handler will scroll when message is appended
            return;
        }
        // reply or reaction forms (contain /reply/ or /react/)
        if (form.action.indexOf('/reply/') !== -1 || form.action.indexOf('/react/') !== -1) {
            e.preventDefault();
            var fd2 = new FormData(form);
            try {
                if (_lastClickedSubmit && _lastClickedSubmit.form === form && _lastClickedSubmit.name) {
                    fd2.append(_lastClickedSubmit.name, _lastClickedSubmit.value);
                }
            } catch (err) {}
            fetch(form.action, { method: 'POST', body: fd2, credentials: 'same-origin' }).then(function(){
                // extract msg idx from action and scroll to it
                var m = form.action.match(/\/(?:reply|react)\/(\d+)/);
                if (m) {
                    var idx = m[1];
                    try { history.replaceState(null, '', '#msg-' + idx); } catch (e) {}
                    var el = document.querySelector('#msg-' + idx);
                    if (el) setTimeout(function(){ try { el.scrollIntoView({behavior:'smooth', block:'center'}); } catch(e){} }, 120);
                }
            }).catch(function(){ /* ignore */ });
            _lastClickedSubmit = null;
            return;
        }
    });

    function escapeHtml(str) {
        return String(str).replace(/[&<>"'`]/g, function (s) {
            return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','`':'&#96;'}[s]);
        });
    }

    function findAllUrls(text) {
        // match http(s) or root-relative paths
        var re = /(?:https?:\/\/\S+|\/[^\s]+)/g;
        var m, out = [];
        while ((m = re.exec(text)) !== null) {
            out.push(m[0].replace(/[.,)]+$/,''));
        }
        return out;
    }

    function isImageUrl(url) {
        if (!url) return false;
        return /\.(png|jpg|jpeg|gif|webp|svg)(\?|$)/i.test(url);
    }

    function youtubeEmbed(url) {
        if (!url) return null;
        var id = null;
        if (url.indexOf('v=') !== -1) {
            id = url.split('v=')[1].split('&')[0];
        } else if (url.indexOf('youtu.be/') !== -1) {
            id = url.split('youtu.be/')[1].split('?')[0];
        }
        return id ? 'https://www.youtube.com/embed/' + encodeURIComponent(id) : null;
    }

    function renderMessageLi(channel, idx, msg) {
        // Build inner .message-text HTML only (used by client when inserting into structured markup)
        var mtext = String(msg.message || '');
        var urls = findAllUrls(mtext);
        var mediaPart = '';
        urls.forEach(function(url){
            if (isImageUrl(url)) {
                mediaPart += '<br><img src="' + escapeHtml(url) + '" alt="image" style="max-width:320px;">';
            } else {
                var yt = youtubeEmbed(url);
                if (yt) {
                    mediaPart += '<br><iframe width="560" height="315" src="' + yt + '" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>';
                }
            }
        });

        var escapedText = escapeHtml(mtext);
        urls.forEach(function(url){
            var safeUrl = escapeHtml(url);
            escapedText = escapedText.replace(escapeHtml(url), '<a href="' + safeUrl + '" target="_blank" rel="noopener">' + safeUrl + '</a>');
        });

        // wrap in message-text container
        var html = '<div class="message-text">' + escapedText + mediaPart + '</div>' +
            '<div style="margin-top:8px;">' +
            '<form method="post" action="/channel/' + encodeURIComponent(channel) + '/react/' + idx + '" style="display:inline;">' +
                ['👍', '😂', '🎉', '😮', '💩'].map(function(emoji){
                    return '<button type="submit" name="reaction" value="' + emoji + '" class="emoji-btn">' + emoji + '</button>';
                }).join('') +
            '</form>' +
            '</div>' +
            renderReactions(msg) +
            '<form method="post" action="/channel/' + encodeURIComponent(channel) + '/reply/' + idx + '" style="margin-top:5px;">' +
                '<input type="text" name="reply_message" placeholder="Reply" required>' +
                '<button type="submit">Reply</button>' +
            '</form>' +
            renderReplies(msg);
        return html;
    }

    // initialize socket
    var socket = io();

    socket.on('connect', function() {
        // no-op; server will pick up session cookie
    });

    socket.on('new_message', function(data) {
        if (data.channel !== currentChannel) return;
        var ul = document.querySelector('.messages');
        if (!ul) return;
        var li = document.createElement('li');
        li.className = 'message' + (data.message.user === window.MC_CONFIG.username ? ' me' : '');
        li.setAttribute('data-msg-idx', data.msg_idx);
        li.id = 'msg-' + data.msg_idx;
        // build avatar HTML preferring server-provided avatar payload
        var avatarHtml = '<div class="avatar">' + escapeHtml((data.message.user||' ')[0]||'?') + '</div>';
        if (data.message && data.message.avatar) {
            var av = data.message.avatar;
            var initials = escapeHtml(av.initials || ((data.message.user||' ')[0]||'?'));
            var bg = escapeHtml(av.bg || '#888');
            var fg = escapeHtml(av.fg || '#fff');
            if (av.url) {
                avatarHtml = '<div class="avatar"><img src="' + escapeHtml(av.url) + '" alt="' + initials + '"/></div>';
            } else {
                avatarHtml = '<div class="avatar" style="background:' + bg + '; color:' + fg + ';">' + initials + '</div>';
            }
        }
        li.innerHTML = avatarHtml + '<div class="message-body">' +
            '<div class="message-header"><div class="message-user">' + escapeHtml(data.message.user) + '</div>' + (data.message.timestamp?(' <div class="timestamp">'+escapeHtml(data.message.timestamp)+'</div>'):'') +'</div>' +
            '<div class="message-text">' + (data.message.rendered || escapeHtml(data.message.message)) + '</div>' +
            '<div style="margin-top:8px;"><form method="post" action="/channel/' + encodeURIComponent(data.channel) + '/react/' + data.msg_idx + '" style="display:inline;">' + ['👍', '😂', '🎉', '😮', '💩'].map(function(emoji){ return '<button type="submit" name="reaction" value="' + emoji + '" class="emoji-btn">' + emoji + '</button>'; }).join('') + '</form></div>' +
            '</div>';
        // render media links using existing renderer and insert
        li.querySelector('.message-text').innerHTML = renderMessageLi(data.channel, data.msg_idx, data.message).replace(/^.*?<div class="message-text">/,'').replace(/<\/div>$/,'');
        ul.appendChild(li);
        // if the new message is from current user, smoothly scroll to it
        if (data.message.user === window.MC_CONFIG.username) {
            setTimeout(function(){
                try { li.scrollIntoView({behavior: 'smooth', block: 'center'}); } catch (e) {}
            }, 80);
        }
    });

    socket.on('update_message', function(data) {
        if (data.channel !== currentChannel) return;
        var ul = document.querySelector('.messages');
        if (!ul) return;
        var selector = '[data-msg-idx="' + data.msg_idx + '"]';
        var li = ul.querySelector(selector);
        if (li) {
            var newReactions = renderReactions(data.message);
            var oldReactions = li.querySelector('.reactions');
            if (oldReactions) {
                oldReactions.outerHTML = newReactions || '';
            } else if (newReactions) {
                var replyForm = li.querySelector('form[action*="/reply/"]');
                if (replyForm) replyForm.insertAdjacentHTML('beforebegin', newReactions);
            }
            var newReplies = renderReplies(data.message);
            var oldReplies = li.querySelector('.replies');
            if (oldReplies) {
                oldReplies.outerHTML = newReplies || '';
            } else if (newReplies) {
                var body = li.querySelector('.message-body');
                if (body) body.insertAdjacentHTML('beforeend', newReplies);
                else li.insertAdjacentHTML('beforeend', newReplies);
            }
        }
    });

    socket.on('presence_update', function(data) {
        if (!Array.isArray(data.active_users)) return;
        var ul = document.getElementById('active-users-list');
        if (!ul) return;
        ul.innerHTML = data.active_users.map(function(u){ return '<li>' + u + '</li>'; }).join('');
    });

    // drag/drop upload support
    function uploadFile(file) {
        var fd = new FormData();
        fd.append('file', file);
        return fetch('/upload_image', { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(function(res){ return res.json(); });
    }

    var dropZone = document.getElementById('drop-zone');
    var fileInput = document.getElementById('file-input');
    if (dropZone) {
        dropZone.addEventListener('dragover', function(e){ e.preventDefault(); dropZone.style.background = '#fff3e0'; });
        dropZone.addEventListener('dragleave', function(e){ e.preventDefault(); dropZone.style.background = '#fffefc'; });
        dropZone.addEventListener('drop', function(e){
            e.preventDefault(); dropZone.style.background = '#fffefc';
            var files = e.dataTransfer.files;
            if (files && files.length) {
                uploadFile(files[0]).then(function(json){
                    if (json && json.url) {
                        // auto-post the uploaded image URL as a message
                        var fd2 = new FormData();
                        fd2.append('message', json.url);
                        fetch('/channel/' + encodeURIComponent(window.MC_CONFIG.channel), { method: 'POST', body: fd2, credentials: 'same-origin' });
                    } else {
                        alert('Upload failed');
                    }
                }).catch(function(){ alert('Upload failed'); });
            }
        });
    }
    if (fileInput) {
        fileInput.addEventListener('change', function(e){
            var f = e.target.files && e.target.files[0];
            if (f) {
                uploadFile(f).then(function(json){
                    if (json && json.url) {
                        var fd2 = new FormData();
                        fd2.append('message', json.url);
                        fetch('/channel/' + encodeURIComponent(window.MC_CONFIG.channel), { method: 'POST', body: fd2, credentials: 'same-origin' });
                    } else { alert('Upload failed'); }
                }).catch(function(){ alert('Upload failed'); });
            }
        });
    }

    // paste-from-clipboard: upload image blobs and post URL
    var messageInput = document.getElementById('message-input');
    function handlePasteEvent(e) {
        var items = (e.clipboardData || (window.clipboardData && window.clipboardData.items));
        if (!items) return;
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            if (it && it.type && it.type.indexOf('image') === 0) {
                var blob = it.getAsFile ? it.getAsFile() : it.getAsBlob();
                if (blob) {
                    e.preventDefault();
                    uploadFile(blob).then(function(json){
                        if (json && json.url) {
                            var fd2 = new FormData();
                            fd2.append('message', json.url);
                            fetch('/channel/' + encodeURIComponent(window.MC_CONFIG.channel), { method: 'POST', body: fd2, credentials: 'same-origin' });
                        } else {
                            alert('Upload failed');
                        }
                    }).catch(function(){ alert('Upload failed'); });
                    return;
                }
            }
        }
    }

    if (messageInput) {
        messageInput.addEventListener('paste', handlePasteEvent);
    } else {
        // fallback: listen on document
        document.addEventListener('paste', handlePasteEvent);
    }

})();
